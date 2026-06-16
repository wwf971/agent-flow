from common import (
  LOCAL_DIR,
  ROOT_DIR,
  build_log_path,
  build_time_stamp,
  extract_markdown_text,
  generate_new_turn_with_live_fetch,
)


def run_example():

  import sys

  if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
  from example_dialogue import example_entries

  selected_entry = example_entries[-1]
  dialogue = list(selected_entry["dialogue"])
  message = selected_entry["message"]
  turn_new, debug_info = generate_new_turn_with_live_fetch(dialogue, message, is_return_debug=True)
  processed_markdown = extract_markdown_text(turn_new[1])

  time_stamp = build_time_stamp()
  path_report = build_log_path(LOCAL_DIR, "agent_report.md", time_stamp=time_stamp)
  with open(path_report, "w", encoding="utf-8") as report_file:
    report_file.write(processed_markdown)

  print("\n----- extraction_debug -----\n")
  print(f"url: {debug_info['url']}")
  print(f"url_extract_method: {debug_info['url_extract_method']}")
  print(f"fetched_char_num: {debug_info['fetched_char_num']}")
  print("fetched_text_preview:")
  print(debug_info["fetched_text_preview"])
  print("\n----- model_request_sent -----\n")
  print(f"model: {debug_info['model_name']}")
  print("contents:")
  print(debug_info["prompt_text"])
  print("\nsystem_instruction:")
  print(debug_info["system_instruction"])
  print("\n----- assistant_raw_reply -----\n")
  print(turn_new[1])
  print("\n----- markdown_you_can_paste -----\n")
  print(processed_markdown)
  print("\n----- saved_file -----\n")
  print(debug_info["path_site_content"])
  print(debug_info["path_model_request"])
  print(str(path_report))


if __name__ == "__main__":
  run_example()
