# MonMiner

A simple terminal dashboard for PRL mining pools.

MonMiner currently supports:

* PearlHash
* MinePRL

This is a personal project and is not an official Pearl tool. Read the code before running it.

## Requirements

Missing dependencies can be installed through `setup.sh`.

* WSL Ubuntu or native Linux
* Python 3
* `tmux`
* NVIDIA GPU + driver
* `nvidia-smi`
* `git`

For MinePRL, Docker with GPU support is required.

## Install

Clone the project:

```bash
git clone https://github.com/viyellaf0rsaken/MonMiner.git
cd MonMiner
chmod +x setup.sh start.sh
bash start.sh
```

`start.sh` will run `setup.sh` first, then launch the dashboard if everything is ready.

During setup, you can choose:

```text
1) PearlHash
2) MinePRL
3) Other pools (unavailable for now)
```

For PearlHash, setup can download `pearl-miner` automatically if it is missing.

## Start after installation

Every time you want to start MonMiner again:

```bash
cd MonMiner
bash start.sh
```

## Update

To update MonMiner:

```bash
cd MonMiner
git pull
bash start.sh
```

## Command console

Inside the dashboard, use the bottom-right command console.

Useful commands:

```text
pause
start
restart
status
explorer
close
show gpu
hide gpu
show wallet
hide wallet
show all
hide all
clear
```

Use:

```text
close
```

to stop mining and close the dashboard.

## Notes
* Multi-GPU support is currently limited. The dashboard may only display the first GPU.
* `runtime/` is local state and should not be uploaded.
* `wallets.json` stores saved wallet labels locally.
* `pearl-miner` is not included in the repo.
* MinePRL uses Docker.
* This tool does not guarantee higher hashrate or higher earnings.
* This project is free. If you paid for it, you were scammed.

## Contact

Discord: `haruka_0wo`

Facebook: `https://www.facebook.com/viyella.f0rsaken`
