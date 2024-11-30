#!/bin/bash

set -euox pipefail

source /opt/Xilinx/Vitis/2023.2/.settings64-Vitis.sh
source /opt/Xilinx/Vivado/2023.2/.settings64-Vivado.sh
source /opt/Xilinx/Vitis_HLS/2023.2/.settings64-Vitis_HLS.sh
source /opt/rust/env
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin/:/usr/bin:/sbin:/bin:$PATH:/opt/oss-cad-suite/bin
export PYTHONPATH=/usr/local/lib/python3.10/dist-packages

# xsct, which is run by the make process, uses Xvfb, which usually needs a
# connection to an X server (even though it is a CLI application). We run
# Xvfb in the container to create a "fake" X session that makes xsct
# happy.
Xvfb :10 &
export DISPLAY=:10

make -C /w
