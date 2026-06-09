import trafilatura


def extract_website_main_content(url):
  try:
    downloaded = trafilatura.fetch_url(url)
  except Exception as e:
    return "", f"Could not access URL. Error: {e}"

  if not downloaded:
    return "", "Could not download content from the URL."

  try:
    text = trafilatura.extract(downloaded)
  except Exception as e:
    return "", f"Could not extract text from the URL. Error: {e}"

  if not text or not text.strip():
    return "", "Could not extract text from the URL."
  return text, ""


def fetch_website_main_content(url, char_num_max=30000):
  text, error = extract_website_main_content(url)
  if error:
    return "", error
  return text[:char_num_max], ""


def tool_web_fetch(url, char_num_max=30000):
  text, error = extract_website_main_content(url)
  if error:
    return {
      "status": "error",
      "error": error,
      "url": url,
    }

  text_visible = text[:char_num_max]
  char_num = len(text_visible)
  is_clipped = len(text) > char_num
  char_index_end = char_num - 1 if char_num > 0 else -1

  # char_num_max limits how many extracted characters are returned to the agent.
  # The current implementation always returns the first range of the extracted text.
  return {
    "status": "success",
    "url": url,
    "text": text_visible,
    "char_num": char_num,
    "char_num_max": char_num_max,
    "is_clipped": is_clipped,
    "char_index_start": 0,
    "char_index_end": char_index_end,
  }
