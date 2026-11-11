"""PyInstaller ve doğrudan çalıştırma için başlatıcı."""
import sys

from oil_analysis.app import main

if __name__ == "__main__":
    sys.exit(main())
