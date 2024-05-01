# Manual installation for Debian/Ubuntu

Follow these instructions if you are encountering issues with the
[installer](install_overview.md#Debian-) or would like to take full control over which components
you want to install.

## Requirements

All AIDE modules (bar the database) require the libraries as specified in the
[requirements.txt](/requirements.txt).

If you have a CUDA-capable GPU it is highly recommended to install PyTorch with GPU support (see the
[official website](https://pytorch.org/get-started/locally/)).


### Compatibility

Below is a compatibility matrix of operating systems (OS), Python, and PyTorch:

| **OS** | **Python** | **PyTorch** | **verified** | **comments** |
|---|---|---|---|---|
| Ubuntu 20.04 LTS to 22.04 LTS | 3.7 to 3.11 | 1.12.1 to 2.3.0 | ✅ | Python 3.10 and above: Detectron2 requires GCC ver. 9 or higher. |
| macOS 11 to 14.4.1 | 3.9 to 3.11 | 2.0.0 to 2.3.0 | ✅ | Python 3.8 and below cause problems with imagecodecs library under macOS with Apple Silicon:  [see here](https://github.com/cgohlke/imagecodecs/issues/72). |
| Microsoft Windows 10 | 3.7 to 3.11 | 1.12.1 to 2.3.0 |  | Requires WSL2 |


_Note:_ You can help complete these compatibility matrices! Since we cannot test every possible
hard- and software combination, we would love to hear feedback regarding experiences and (in-)
compatibilities. Please report the following:
* Installation log (as produced by the installer)
* Terminal/command line output (as much as is available; make sure to remove sensitive information)
* Information about your operating system (Linux: `uname -a`; macOS: `sw_vers`), as well as versions
  of Python (`python -V`) and CUDA (`nvidia-smi`).

Thank you very much!



## Step-by-step installation

The following installation routine requires Debian-based GNU/Linux distributions. It has been tested
on Ubuntu 20.04. AIDE will likely run on different OS as well, with instructions requiring
corresponding adaptations.



### Prepare environment

Run the following code snippets on all machines that run one of the services for AIDE (_LabelUI_,
_AIController_, _AIWorker_, etc.). It is strongly recommended to run AIDE in a self-contained Python
environment, such as [Conda](https://conda.io/) (recommended and used below) or
[Virtualenv](https://virtualenv.pypa.io).

```bash
    # specify the root folder where you wish to install AIDE
    targetDir=/path/to/desired/source/folder

    # create environment (requires conda or miniconda)
    conda create -y -n aide python=3.9
    conda activate aide

    # download AIDE source code
    sudo apt-get update && sudo apt-get install -y git
    cd $targetDir
    git clone https://github.com/bkellenb/AIDE.git

    # install required libraries
    sudo add-apt-repository -y ppa:ubuntugis/ppa && sudo apt-get update
    sudo apt-get install -y build-essential wget libpq-dev python3 ffmpeg libsm6 libxext6 libglib2.0-0 python3-opencv python3-pip gdal-bin libgdal-dev

    # install PyTorch first (required dependency for other packages)
    pip install -y pyyaml
    $(python install/get_pytorch_version.py --format=conda --with-cuda=1)

    # install Detectron2
    pip install git+https://github.com/facebookresearch/detectron2.git

    # install all the remaining requirements
    pip install -U -r requirements.txt
```

Note: script `install/get_pytorch_version.py` attempts to auto-detect compatible PyTorch and
Torchvision versions based on currently installed Python version (and CUDA, if available and
specified). If this fails, you may try and install PyTorch and dependencies manually as per
[official guidelines](https://pytorch.org/get-started/previous-versions/).


### Create the settings.ini file

Every instance running one of the services for AIDE gets its general required properties from a
*.ini file. It is highly recommended to prepare a .ini file at the start of the installation of AIDE
and to have a copy of the same file on all machines. Note that in the latest version of AIDE, the
.ini file does not contain any project-specific parameters anymore. **Important: NEVER, EVER make
the configuration file accessible to anyone, let alone the network or Web.**

1. Create a *.ini file for your general AIDE setup. See the provided file under
   `config/settings.ini` for an example. To view all possible parameters, see
   [here](configure_settings.md).
2. Copy the *.ini file to each server instance.
3. On each instance, set the `AIDE_CONFIG_PATH` environment variable to point to your *.ini file:
```bash
    # temporarily:
    export AIDE_CONFIG_PATH=/path/to/settings.ini

    # permanently (requires re-login):
    echo "export AIDE_CONFIG_PATH=path/to/settings.ini" | tee ~/.profile
```


### Set up the database instance

See [here](setup_db.md)



### Set up the message broker

The message broker is required for all services of AIDE, except for the Database.
To set up the message broker correctly, see [here](installation_aiTrainer.md).





### Import existing data

In the latest version, AIDE offers a GUI solution to configure projects and import and export
images. At the moment, previous data management scripts listed [here](import_data.md) only work if
the configuration .ini file contains all the legacy, project-specific parameters required for the
previous version of AIDE. New API scripts are under development.



### Launch the modules

See [here](launch_aide.md)
