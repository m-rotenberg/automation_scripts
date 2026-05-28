# Notebooks Usage ReadMe

The notebooks in this repository are ready to use.

Before running any notebook, ensure you have a .env file available with the required environment variables and credentials. The notebooks load configuration from the .env file and do not require secrets to be hardcoded.

As long as the notebook is pointed to a valid .env file, no additional setup is required.

# Environment Variables

All sensitive configuration (API keys, tokens, account IDs, etc.) must be provided via a .env file.

The .env file is intentionally not included in this repository and should never be committed to version control.

# Notes

Notebooks assume they are run from the repository root

If you run a notebook from a subdirectory, ensure the .env path is resolved correctly

# Disclaimer

This repository is intended for internal automation and experimentation only and is not intended for production use. Scripts and notebooks are provided as-is, without guarantees of stability or support.
