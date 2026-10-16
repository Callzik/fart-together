from setuptools import setup

setup(
    name="FartTogether",
    version="2.0",
    options={
        "build_apps": {
            "gui_apps": {"FartTogether": "fart_together.py"},
            "include_patterns": ["assets/*.ttf", "assets/*.txt", "assets/sfx/*.wav"],
            "plugins": ["pandagl", "p3openal_audio"],
            "platforms": ["win_amd64"],
            "log_filename": "$USER_APPDATA/FartTogether/output.log",
            "log_append": False,
        }
    },
)
