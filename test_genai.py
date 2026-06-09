import importlib.util
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
LOCAL_SCRIPT_PATH = ROOT_DIR / "test" / "_0_web_fetch_local" / "test.py"


def _load_local_script_module():
  module_name = "web_fetch_local_test"
  module_spec = importlib.util.spec_from_file_location(module_name, str(LOCAL_SCRIPT_PATH))
  if module_spec is None or module_spec.loader is None:
    raise ImportError(f"Could not load module from {LOCAL_SCRIPT_PATH}")
  module = importlib.util.module_from_spec(module_spec)
  module_spec.loader.exec_module(module)
  return module


def generate_new_turn_with_live_fetch(
  dialogue,
  message,
  is_return_debug=False,
  log_dir=None,
  isReturnDebug=None,
):
  if isReturnDebug is not None:
    is_return_debug = isReturnDebug
  module = _load_local_script_module()
  return module.generate_new_turn_with_live_fetch(
    dialogue,
    message,
    is_return_debug=is_return_debug,
    log_dir=log_dir,
  )


def extract_markdown_text(reply_text):
  module = _load_local_script_module()
  return module.extract_markdown_text(reply_text)


def run_example():
  module = _load_local_script_module()
  module.run_example()


if __name__ == "__main__":
  run_example()
