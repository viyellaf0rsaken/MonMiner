# MonMiner

All-in-one terminal dashboard for Pearl/PRL mining pools with GPU stats, live logs, wallet links, and basic miner controls.

MonMiner currently supports:

* PearlHash
* MinePRL

This is just a personal project and is not an official Pearl tool.

## Requirements

Missing dependencies can be installed or checked through `setup.sh`.

* WSL Ubuntu or native Linux
* Python 3
* `tmux`
* NVIDIA GPU + driver
* `nvidia-smi`
* `git`

Extra requirements:

* PearlHash: `pearl-miner`
* MinePRL: Docker with NVIDIA GPU support

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

MinePRL uses Docker and will start the official MinePRL worker container.

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

## Dashboard layout

MonMiner uses a `tmux` layout:

```text
dashboard | live miner log
          | command console
```

The dashboard reads runtime state from local files. Pool-specific backends write data into `runtime/current_data.json`.

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
perf on
perf off
clear
```

Use:

```text
close
```

to stop mining and close the dashboard.

## Performance Mode

Performance Mode is optional.

It can be toggled from the command console:

```text
perf on
perf off
```

Depending on your Windows/WSL setup, it may try to apply mining-focused settings such as power plan, display mode, or desktop background changes.

Performance Mode should restore settings when you run:

```text
perf off
```

or close the dashboard normally.

## Local files

These files are generated locally and should not be uploaded:

```text
runtime/
wallets.json
pearl-miner
*.log
```

Notes:

* `runtime/` stores temporary dashboard state.
* `wallets.json` stores saved wallet labels locally.
* `pearl-miner` is not included in the repo.
* MinePRL uses Docker.
* Multi-GPU display is currently limited and may only show the first GPU.
* This tool does not guarantee higher hashrate or higher earnings.
* This project is free. If you paid for it, you were scammed.

## Troubleshooting

Stop a stuck tmux session:

```bash
tmux kill-server
```

Reset local runtime state:

```bash
rm -rf runtime
bash start.sh
```

Check Python syntax:

```bash
python3 -m py_compile dashboard.py cmd.py minerlog.py pearlhash_data.py mineprl_data.py performance.py
```

Check GPU stats manually:

```bash
nvidia-smi
```

Check live miner log:

```bash
tail -f runtime/miner.log
```

## Contact

Discord: `haruka_0wo`

Facebook: `https://www.facebook.com/viyella.f0rsaken`
