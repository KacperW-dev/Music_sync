# Music Sync

A simple Python desktop utility for syncing your local music library to a remote server over SSH/SFTP.

It compares the local folder against the remote destination and copies only the files that are missing, with an option to overwrite existing remote files if you want.

## Features

- Select a local music folder from your computer
- Enter SSH details for the remote server
- Connect securely using an SSH key or password
- Compare local and remote files
- Copy only missing files by default
- Optionally overwrite existing remote files
- Progress and activity logging built into the GUI

## Requirements

This project uses:

- Python 3
- Tkinter for the graphical interface
- Paramiko for SSH/SFTP communication

## Install dependencies

### Arch Linux

```bash
sudo pacman -S tk python-paramiko
```

If you are using a virtual environment, you can also install Paramiko with pip:

```bash
python3 -m pip install paramiko
```

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install python3-tk python3-pip
python3 -m pip install paramiko
```

### Fedora

```bash
sudo dnf install python3-tkinter python3-pip
python3 -m pip install paramiko
```

## Run the app

```bash
python3 music_sync.py
```
## Notes

- The app expects a valid SSH server and a writable remote music directory.
- The remote path is usually something like `/home/username/Music`.
- For most setups, an SSH private key is the easiest authentication method.
- This tool is meant for syncing music files to a remote server; it is not limited to Jellyfin.

## License

This project is provided as-is for personal use.
