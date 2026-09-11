#!/usr/bin/env ruby
# frozen_string_literal: true

require "csv"
require "json"
require "fileutils"

SUMMARY = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/path_following_geometry_m50_20260910/summary.tsv"
LOG_DIR = File.dirname(SUMMARY)
RESULTS_ROOT = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
OUT_DIR = File.expand_path("../recovery/path_following_geometry_m50_20260910", __dir__)

EXTRA_HEADERS = %w[
  recovery_status
  recovery_source
  last_observed_step
  last_observed_distance_to_start
  recovery_note
].freeze

def measurement_for(ep)
  pattern = File.join(
    RESULTS_ROOT,
    "*path_following_geometry_m50_20260910_ep#{ep}",
    "measurements",
    "*.json"
  )
  Dir.glob(pattern).max_by { |path| File.mtime(path) }
end

def extract_terminal_fields(text)
  fields = {}
  %w[outbound_success return_success round_trip_success].each do |key|
    values = text.scan(/"#{key}"\s*:\s*(true|false)/)
    fields[key] = values.last.first.capitalize unless values.empty?
  end
  values = text.scan(/"distance_to_start"\s*:\s*(-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)/)
  fields["distance_to_start"] = values.last.first unless values.empty?
  fields
end

def last_logged_ground_truth(log)
  matches = log.scan(
    /\[return\] step=(\d+), elapsed_return_steps=\d+, distance_to_start=([0-9.]+)/
  )
  matches.last || [nil, nil]
end

def outbound_stop_distance(log)
  matches = log.scan(
    /\[return\] start step=\d+.*?pose_error_after_oracle=\{[^}]*?'xy_error_m':\s*([0-9.]+)/
  )
  matches.empty? ? nil : matches.last.first
end

rows = CSV.read(SUMMARY, headers: true, col_sep: "\t")
headers = rows.headers + EXTRA_HEADERS
recovered = []

rows.each do |row|
  ep = row["episode_idx"]
  status = "original_summary"
  source = row["measurement_file"].to_s
  last_step = nil
  last_distance = nil
  note = ""

  if row["exit_code"] == "0" && row["round_trip_success"].to_s.empty?
    measurement = measurement_for(ep)
    if measurement
      text = File.read(measurement, encoding: "UTF-8")
      begin
        data = JSON.parse(text)
        rt = data.fetch("round_trip", {})
        %w[outbound_success return_success round_trip_success distance_to_start outbound_stop_distance_to_goal trajectory_record_count].each do |key|
          row[key] = rt[key].to_s unless rt[key].nil?
        end
        row["measurement_file"] = measurement
        status = "valid_measurement_reparsed"
      rescue JSON::ParserError => error
        terminal = extract_terminal_fields(text)
        raise "No recoverable terminal outcome in #{measurement}" unless terminal.keys.sort == %w[distance_to_start outbound_success return_success round_trip_success].sort

        terminal.each { |key, value| row[key] = value }
        row["measurement_file"] = measurement
        status = "corrupt_measurement_terminal_fields_recovered"
        source = measurement
        note = "Terminal round_trip fields recovered verbatim; JSON remains corrupt: #{error.message.lines.first.strip}"
      end
    else
      log_path = File.join(LOG_DIR, "ep#{ep}_eval.log")
      log = File.read(log_path, encoding: "UTF-8", invalid: :replace, undef: :replace)
      raise "Episode #{ep} never entered return" unless log.include?("[return] start step=")
      raise "Episode #{ep} contains a non-pass stop-gate decision" if log.match?(/\[stop_gate\].*decision=(?!pass\b)/)

      outbound_distance = outbound_stop_distance(log)
      raise "Episode #{ep} lacks outbound stop distance" unless outbound_distance

      row["outbound_stop_distance_to_goal"] = outbound_distance
      row["outbound_success"] = (outbound_distance.to_f < 3.0).to_s.capitalize
      row["return_success"] = "False"
      row["round_trip_success"] = "False"
      last_step, last_distance = last_logged_ground_truth(log)
      status = "missing_measurement_outcome_recovered_from_log"
      source = log_path
      note = "Success flags recovered from control flow. Outbound uses logged XY error against the batch 3.0 m success radius; no accepted return stop occurred. Last distance is telemetry, not necessarily the terminal distance."
    end
  elsif row["exit_code"] != "0"
    status = "infrastructure_failure_not_recovered"
    source = File.join(LOG_DIR, "ep#{ep}_vlm.log")
    note = "Evaluator did not run; navigation outcome is unavailable."
  end

  row["recovery_status"] = status
  row["recovery_source"] = source
  row["last_observed_step"] = last_step
  row["last_observed_distance_to_start"] = last_distance
  row["recovery_note"] = note
  recovered << row
end

FileUtils.mkdir_p(OUT_DIR)
output = File.join(OUT_DIR, "summary.recovered.tsv")
CSV.open(output, "w", col_sep: "\t", write_headers: true, headers: headers) do |csv|
  recovered.each { |row| csv << headers.map { |header| row[header] } }
end

evaluable = recovered.select { |row| row["exit_code"] == "0" }
raise "Expected 48 evaluable rows, got #{evaluable.length}" unless evaluable.length == 48
raise "Recovery left blank outcomes" if evaluable.any? { |row| row["round_trip_success"].to_s.empty? }

puts output
puts "evaluable=#{evaluable.length}"
puts "round_trip_success=#{evaluable.count { |row| row["round_trip_success"] == "True" }}"
puts "round_trip_failure=#{evaluable.count { |row| row["round_trip_success"] == "False" }}"
puts "corrupt_measurements_recovered=#{recovered.count { |row| row["recovery_status"].start_with?("corrupt_measurement") }}"
puts "missing_measurements_recovered=#{recovered.count { |row| row["recovery_status"].start_with?("missing_measurement") }}"
puts "infrastructure_failures=#{recovered.count { |row| row["recovery_status"].start_with?("infrastructure_failure") }}"
