# Entry point for the KBD-Builder executable (PyInstaller can't start a package's __main__ directly)
from builder.__main__ import main

main()
