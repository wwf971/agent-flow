import os
from pathlib import Path

# python >= 3.11
# python -m pip install langchain langchain-core langchain-google-genai

from langchain_core.messages import AIMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from example_dialogue import example_entries


def load_config_value(config_key):
  root_dir = Path(__file__).resolve().parent
  config_paths = [
    root_dir / "config" / "config.yaml",
    root_dir / "config.yaml",
  ]
  for config_path in config_paths:
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


def generate_new_turn(dialogue, message):
  api_key = load_config_value("google_api_key") or os.getenv("GOOGLE_API_KEY")
  configured_model = load_config_value("google_model") or "gemini-2.5-flash"
  if not api_key:
    raise ValueError(
      "Please set google_api_key in config/config.yaml (or config.yaml) "
      "or GOOGLE_API_KEY in your environment."
    )

  history = []
  for user_message, assistant_message in dialogue:
    history.append(HumanMessage(content=user_message))
    history.append(AIMessage(content=assistant_message))

  candidate_models = [
    configured_model,
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
  ]

  tried_models = []
  last_error = None
  response = None

  for model_name in candidate_models:
    if model_name in tried_models:
      continue
    tried_models.append(model_name)
    model = ChatGoogleGenerativeAI(
      model=model_name,
      google_api_key=api_key,
      temperature=0.2,
    )
    try:
      response = model.invoke(history + [HumanMessage(content=message)])
      break
    except Exception as e:
      error_message = str(e)
      if "NOT_FOUND" in error_message:
        last_error = e
        continue
      raise

  if response is None:
    raise ValueError(
      "No available model found. "
      f"Tried: {', '.join(tried_models)}. "
      "Set google_model in config/config.yaml to a model available for your account."
    ) from last_error
  reply = response.content
  turn_new = (message, reply)
  dialogue.append(turn_new)
  return turn_new


if __name__ == "__main__":
  selected_entry = example_entries[-1]
  dialogue = list(selected_entry["dialogue"])
  message = selected_entry["message"]
  turn_new = generate_new_turn(dialogue, message)
  print(turn_new)