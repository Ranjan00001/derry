from setuptools import setup, find_packages

setup(
    name="derry",
    version="0.1.0",
    description="Desktop AI Agent for Linux",
    # find_packages() automatically finds the 'derry' folder 
    packages=find_packages(),
    install_requires=[
        "PyQt6>=6.0.0",
        "google-generativeai>=0.3.0",
        "vosk>=0.3.45",
        "python-dotenv>=1.0.0",
        "sounddevice>=0.4.6"
    ],
    entry_points={
        "console_scripts": [
            "derry=derry.__main__:main",
        ],
    },
)
