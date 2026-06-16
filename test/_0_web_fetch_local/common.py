import os
import sys
from datetime import datetime
from pathlib import Path

# python -m pip install google-genai requests trafilatura beautifulsoup4
import requests
from bs4 import BeautifulSoup

ROOT_DIR = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
  sys.path.insert(0, str(ROOT_DIR))
from api_llm import generate_text
from backend_api_log import print_backend_log_result, try_log_dialogue_to_backend
from tool_web_fetch import fetch_website_main_content

DEFAULT_CONFIG_PATHS = [
  ROOT_DIR / "config" / "config.0.yaml",
  ROOT_DIR / "config" / "config.yaml",
  ROOT_DIR / "config.yaml",
]


def load_config_value(config_key, config_paths=None):
  paths = config_paths or DEFAULT_CONFIG_PATHS
  for config_path in paths:
    if not config_path.exists():
      continue
    with open(config_path, "r", encoding="utf-8") as config_file:
      for raw_line in config_file:
        line = raw_line.strip()
        if not line or line.startswith("#"):
          continue
        if not line.startswith(f"{config_key}:"):
          continue
        value = line.split(":", 1)[1].strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
          value = value[1:-1]
        return value
  return ""


def build_prompt_with_history(dialogue, message):
  lines = ["You are a helpful assistant."]
  for user_message, assistant_message in dialogue:
    lines.append(f"User: {user_message}")
    lines.append(f"Assistant: {assistant_message}")
  lines.append(f"User: {message}")
  return "\n".join(lines)


def extract_markdown_text(reply_text):
  text = (reply_text or "").strip()
  if not text:
    return ""

  fence_markdown = "```markdown"
  start_markdown = text.find(fence_markdown)
  if start_markdown != -1:
    content_start = start_markdown + len(fence_markdown)
    end_markdown = text.find("```", content_start)
    if end_markdown != -1:
      return text[content_start:end_markdown].strip()

  fence_plain = "```"
  start_plain = text.find(fence_plain)
  if start_plain != -1:
    content_start = start_plain + len(fence_plain)
    end_plain = text.find("```", content_start)
    if end_plain != -1:
      return text[content_start:end_plain].strip()

  return text


def fetch_live_transit_text_bs(url):
  headers = {
    "User-Agent": (
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
  }
  try:
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code != 200:
      return "", f"Could not access URL. HTTP status: {response.status_code}"
  except Exception as e:
    return "", f"Could not access URL. Error: {e}"

  soup = BeautifulSoup(response.text, "html.parser")
  parts = []
  title = soup.title.get_text(strip=True) if soup.title else ""
  if title:
    parts.append(f"[title]\n{title}")

  major_selectors = [
    "main",
    "#contents",
    "#contentsWrap",
    "#main",
    ".contents",
    ".content",
    ".mdServiceStatus",
    "#mdServiceStatus",
    ".elmTrouble",
    ".dataTbl",
    ".mdListTrain",
  ]

  seen_text = set()
  for selector in major_selectors:
    blocks = soup.select(selector)
    for block in blocks:
      text = block.get_text(separator="\n", strip=True)
      if not text:
        continue
      compact_text = " ".join(text.split())
      if len(compact_text) < 40:
        continue
      if compact_text in seen_text:
        continue
      seen_text.add(compact_text)
      parts.append(f"[section: {selector}]\n{text}")

  combined_text = "\n\n".join(parts).strip()
  if combined_text:
    return combined_text[:30000], ""

  full_text = soup.get_text(separator="\n", strip=True)
  if not full_text.strip():
    return "", "Could not extract text from the URL."
  return full_text[:30000], ""


def fetch_live_transit_text_trafilatura(url):
  return fetch_website_main_content(url)


def fetch_live_transit_text(url, url_extract_method="trafilatura"):
  method = (url_extract_method or "").strip().lower()
  if method == "trafilatura":
    return fetch_live_transit_text_trafilatura(url)
  if method == "bs":
    return fetch_live_transit_text_bs(url)
  return "", f"Unsupported url_extract_method: {url_extract_method}. Use 'trafilatura' or 'bs'."


def build_time_stamp(time_value=None):
  time_local = time_value or datetime.now().astimezone()
  milli_10 = time_local.microsecond // 10000
  offset = time_local.utcoffset()
  offset_hours = int(offset.total_seconds() // 3600) if offset else 0
  offset_sign = "+" if offset_hours >= 0 else "-"
  offset_value = f"{abs(offset_hours):02d}"
  return f"{time_local:%Y%m%d_%H%M%S}{milli_10:02d}{offset_sign}{offset_value}"


def build_log_path(log_dir, file_name_tail, time_stamp=None):
  stamp = time_stamp or build_time_stamp()
  return Path(log_dir) / f"{stamp}_{file_name_tail}"


def save_fetched_text(output_path, target_url, url_extract_method, fetched_text, fetch_error):
  fetched_at = datetime.now().astimezone().isoformat()
  lines = [
    f"fetched_at_local: {fetched_at}",
    f"url: {target_url}",
    f"url_extract_method: {url_extract_method}",
  ]
  if fetch_error:
    lines.append(f"error: {fetch_error}")
    lines.append("")
    lines.append("fetched_text:")
    lines.append("")
  else:
    lines.append("error: ")
    lines.append("")
    lines.append("fetched_text:")
    lines.append(fetched_text)
  content = "\n".join(lines)
  with open(output_path, "w", encoding="utf-8") as output_file:
    output_file.write(content)


def save_model_request_text(output_path, model_name, prompt_text, system_instruction):
  lines = [
    "model_request:",
    f"model: {model_name}",
    "",
    "contents:",
    prompt_text,
    "",
    "system_instruction:",
    system_instruction,
    "",
    "temperature: 0.0",
  ]
  content = "\n".join(lines)
  with open(output_path, "w", encoding="utf-8") as output_file:
    output_file.write(content)


def generate_new_turn_with_live_fetch(
  dialogue,
  message,
  is_return_debug=False,
  log_dir=None,
  isReturnDebug=None,
):
  if isReturnDebug is not None:
    is_return_debug = isReturnDebug
  api_key = load_config_value("google_api_key") or os.getenv("GOOGLE_API_KEY")
  provider_name = load_config_value("llm_provider") or "google"
  model_name = load_config_value("google_model") or "gemini-2.5-flash"
  url_extract_method = load_config_value("url_extract_method") or "trafilatura"
  target_url = load_config_value("target_url") or "https://transit.yahoo.co.jp/diainfo/area/4"
  if not api_key:
    raise ValueError(
      "Please set google_api_key in config/config.yaml (or config.yaml) "
      "or GOOGLE_API_KEY in your environment."
    )

  log_dir_path = Path(log_dir) if log_dir else LOCAL_DIR
  log_dir_path.mkdir(parents=True, exist_ok=True)

  clean_message = message
  live_text, fetch_error = fetch_live_transit_text(target_url, url_extract_method=url_extract_method)

  time_stamp = build_time_stamp()
  path_site_content = build_log_path(log_dir_path, "site_content.md", time_stamp=time_stamp)
  save_fetched_text(path_site_content, target_url, url_extract_method, live_text, fetch_error)

  debug_info = {
    "url": target_url,
    "url_extract_method": url_extract_method,
    "fetch_error": fetch_error,
    "fetched_char_num": len(live_text),
    "fetched_text_preview": live_text[:1200],
    "path_site_content": str(path_site_content),
  }
  if fetch_error:
    reply = f"I could not retrieve live data from {target_url}. {fetch_error}"
    turn_new = (clean_message, reply)
    dialogue.append(turn_new)
    backend_log_result = try_log_dialogue_to_backend(
      dialogue,
      metadata={
        "title": "_0_web_fetch_local fetch error",
        "sourceText": "_0_web_fetch_local",
      },
    )
    print_backend_log_result(backend_log_result)
    debug_info["backend_log_result"] = backend_log_result
    if is_return_debug:
      return turn_new, debug_info
    return turn_new

  prompt_text = build_prompt_with_history(dialogue, clean_message)
  system_instruction = (
    f"You must answer only from the fetched live text from {target_url}. "
    "If the live text does not contain enough information, state that clearly. "
    "Do not guess. "
    f"Fetched live text: {live_text}"
  )

  path_model_request = build_log_path(log_dir_path, "model_request.md", time_stamp=time_stamp)
  save_model_request_text(path_model_request, model_name, prompt_text, system_instruction)

  debug_info["model_name"] = model_name
  debug_info["prompt_text"] = prompt_text
  debug_info["system_instruction"] = system_instruction
  debug_info["path_model_request"] = str(path_model_request)

  reply = generate_text({
    "providerName": provider_name,
    "apiKey": api_key,
    "modelName": model_name,
    "textInput": prompt_text,
    "systemInstruction": system_instruction,
    "temperature": 0.0,
  })
  turn_new = (clean_message, reply)
  dialogue.append(turn_new)
  backend_log_result = try_log_dialogue_to_backend(
    dialogue,
    metadata={
      "title": "_0_web_fetch_local live fetch",
      "sourceText": "_0_web_fetch_local",
    },
  )
  print_backend_log_result(backend_log_result)
  debug_info["backend_log_result"] = backend_log_result
  if is_return_debug:
    return turn_new, debug_info
  return turn_new
