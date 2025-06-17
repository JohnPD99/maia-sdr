# Maia SDR ADALM Pluto firmware

This repository contains the modified ADALM Pluto firmware for the
[Maia SDR](https://maia-sdr.org) project. See
[analogdevicesinc/plutosdr-fw](https://github.com/analogdevicesinc/plutosdr-fw)
for the default ADI firmware.

Latest binary Release : [![GitHub Release](https://img.shields.io/github/release/maia-sdr/plutosdr-fw.svg)](https://github.com/maia-sdr/plutosdr-fw/releases/latest)  [![Github Releases](https://img.shields.io/github/downloads/maia-sdr/plutosdr-fw/total.svg)](https://github.com/maia-sdr/plutosdr-fw/releases/latest)

Firmware License : [![Many Licenses](https://img.shields.io/badge/license-LGPL2+-blue.svg)](https://github.com/analogdevicesinc/plutosdr-fw/blob/master/LICENSE.md)  [![Many License](https://img.shields.io/badge/license-GPL2+-blue.svg)](https://github.com/analogdevicesinc/plutosdr-fw/blob/master/LICENSE.md)  [![Many License](https://img.shields.io/badge/license-BSD-blue.svg)](https://github.com/analogdevicesinc/plutosdr-fw/blob/master/LICENSE.md)  [![Many License](https://img.shields.io/badge/license-apache-blue.svg)](https://github.com/analogdevicesinc/plutosdr-fw/blob/master/LICENSE.md) and many others.

## Installation and supported hardware

This repository contains Maia SDR firmware images for the ADI Pluto and the
Pluto+.

See the [installation instructions](https://maia-sdr.org/installation/) for how
to install the firmware and for other supported devices.

## Support

Support is handled through Github issues or dicussions. Issues dealing with the ADALM Pluto
firmware itself (building the firmware, flashing the firmware, etc.) should go
as
[issues in the plutosdr-fw repository](https://github.com/maia-sdr/plutosdr-fw/issues).
Issues having to do with Maia SDR (software or FPGA bugs, features requests, etc.)
should go as [issues in the maia-sdr repository](https://github.com/maia-sdr/maia-sdr/issues).
There are also
[Github discussions in the maia-sdr repository](https://github.com/maia-sdr/maia-sdr/discussions)
for any topics which are not issues (general questions, comments, etc.).

## Build instructions
### Estevez Instructions

Using the `ghcr.io/maia-sdr/maia-sdr-devel` Docker image from
[maia-sdr-docker](https://github.com/maia-sdr/maia-sdr-docker) is recommended to build
the firmware. To build the FPGA bitstream, Vivado 2023.2 is required.

Once the environment variables and `PATH` have been set as indicated in the
[Docker container README](https://github.com/maia-sdr/maia-sdr-docker#readme),
the firmware can be built using
```
make
```

It is also possible to build using `docker compose` by running
```
DOCKER_USER="$(id -u):$(id -g)" TARGET=pluto docker compose run --rm build
```

### Custom Instructions
#### 🛠️ Building Custom Firmware Using a Forked `maia-sdr` Monorepo

This guide explains how to use a **custom fork of the full `maia-sdr` monorepo** inside your own `plutosdr-fw` fork, and build firmware using Docker and Vivado.

---

##### 📦 1. Fork Repositories

You need to fork the following GitHub repositories:

- [`maia-sdr/plutosdr-fw`](https://github.com/maia-sdr/plutosdr-fw) → `youruser/plutosdr-fw`
- [`maia-sdr/maia-sdr`](https://github.com/maia-sdr/maia-sdr) → `youruser/maia-sdr`

---

##### 🔧 2. Replace the `maia-sdr` Submodule

From the root of your cloned `plutosdr-fw` repo:

```bash
# Remove existing submodule
git submodule deinit -f maia-sdr
git rm -f maia-sdr
rm -rf .git/modules/maia-sdr

# Add your custom fork as submodule
git submodule add git@github.com:youruser/maia-sdr.git maia-sdr
git submodule update --init --recursive

# Optional: switch to your working branch
cd maia-sdr
git checkout -b my-custom-branch
cd ..

# Commit the updated submodule reference
git add maia-sdr
git commit -m "Use custom fork of maia-sdr monorepo"
git push origin main
```

> ✅ After this, your firmware build will use your custom `maia-hdl`, `maia-httpd`, etc. from the full monorepo.

---

##### 🐳 3. Set Up Docker & Install Vivado 2023.2

> 💡 You must manually install Vivado due to licensing.

###### a. Pull the development container and create volume:

```bash
sudo docker pull ghcr.io/maia-sdr/maia-sdr-devel:latest
sudo docker volume create vivado2023_2
```

###### b. Run Docker with GUI support:

```bash
xhost +local:  # for Vivado GUI support

docker run --rm --net host -e DISPLAY=$DISPLAY -e TERM \
  --name=maia-sdr-devel --hostname=maia-sdr-devel \
  --ulimit "nofile=1024:1048576" \
  -v vivado2023_2:/opt/Xilinx \
  -v $HOME/maia-fw:/hdl \
  -it ghcr.io/maia-sdr/maia-sdr-devel
```

> 💡 You can mount a subdirectory of `$HOME` for safety (like `$HOME/maia-fw`) instead of the whole home directory.

###### c. Install Vivado inside the container

In a second terminal:

```bash
sudo docker exec -u 0 -it maia-sdr-devel /bin/bash
```

Then:

```bash
cd /home/ubuntu
chmod +x FPGAs_AdaptiveSoCs_Unified_2023.2_1013_2256_Lin64.bin
./FPGAs_AdaptiveSoCs_Unified_2023.2_1013_2256_Lin64.bin
```

- Select "Do not upgrade"
- Choose: VITIS, Vivado, Vitis HLS, Devices for Custom Platforms (SoCs only)
- Install to `/opt/Xilinx` (mapped to Docker volume)

---

##### ⚙️ 4. Configure the Environment Inside the Container

Set up the environment for building:

```bash
cat >> ~/.bashrc
# Paste the following, then press Ctrl+D
source /opt/Xilinx/Vivado/2023.2/settings64.sh
source /opt/rust/env
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin/:/usr/bin:/sbin:/bin:/opt/gcc-arm-linux-gnueabi/bin:$PATH:/opt/oss-cad-suite/bin
```

Apply changes immediately:

```bash
source ~/.bashrc
```

---

##### 🧪 5. Build the Firmware

Inside the Docker container:

```bash
cd /hdl/plutosdr-fw
make
```

This will:

- Use your custom `maia-sdr` contents (`maia-hdl`, `maia-httpd`, etc.)
- Build the firmware and place output in `build/`

---

##### ⚡ Optional: Headless Build Using Docker Compose

You can also build the firmware using the automated Docker Compose setup:

```bash
cd /hdl/plutosdr-fw
./build-docker.sh
```

> ✅ No `xhost`, GUI, or manual container steps required.  
> 🧪 Matches the GitHub Actions CI environment.

---

##### 🔁 Updating Your Submodule

If you push changes to your custom `maia-sdr` fork:

```bash
cd maia-sdr
git pull origin my-custom-branch
cd ..
git add maia-sdr
git commit -m "Update submodule to latest commit"
git push
```

---

##### 🧠 Notes

- GitHub will show the submodule (`maia-sdr`) as a single clickable entry, not its contents.
- The actual files live in the linked repo.
- You can avoid these submodule complexities by flattening the repo, but this is **not recommended** for long-term development.

---

##### ✅ Summary

| Task                             | Tool/Repo                  |
|----------------------------------|-----------------------------|
| Customize HDL, HTTP, etc.        | `maia-sdr` (monorepo)       |
| Wire it into firmware build      | `plutosdr-fw` via submodule |
| Build interactively with GUI     | Docker + Vivado             |
| Build headlessly / CI-style      | `./build-docker.sh`         |
 
## Pluto+

**Disclaimer:** The Maia SDR project acknowledges that the name Pluto+ is
  unfortunate, because this hardware device is unrelated to Analog Devices
  ADALM products. However, this device is not known by any other name, so us
  referring to it in another way would have been very confusing. Therefore,
  within Maia SDR, the firmware build for the Pluto+ is refered to as Pluto+ or
  `plutoplus`.

Here are some notes about the Pluto+ Maia SDR firmware.

The Pluto+ is largerly compatible with the ADALM-Pluto in terms of firmware. It
uses a different Zynq 7010 package and FPGA pinout, but its pinout ensures that
all the signals go to the same FPGA wirebonding pads (even though the BGA pins
are called differently and placed differently in the package). This means that a
regular ADALM-Pluto firmware mostly works on the Pluto+, though Ethernet and the
SD card will not work because the ADALM-Pluto does not have this hardware. There
is one pinout difference between the ADALM-Pluto and the Pluto+: the USB PHY
reset (URST) on the ADALM-Pluto is connected to MIO52. On the Pluto+ it is
usually connected to MIO46, because MIO52 is required for the Ethernet
MDIO. However, the Pluto+ has a jumper to allow connecting the USB PHY reset to
MIO52 instead when a firmware for the ADALM-Pluto (which does not support
Ethernet) is used (see the [plutoplus
README](https://github.com/plutoplus/plutoplus/tree/master#jumpers-and-pinouts)). When
using the Pluto+ Maia SDR firmware, it is required to connect the jumper to
MIO46.

There is usually no point in using the ADALM-Pluto Maia SDR firmware in a
Pluto+. Generally, the Pluto+ Maia SDR firmware should be used, as it supports
Ethernet and the SD card.

In order to distinguish it from the ADALM-Pluto firmware, the files for the
Pluto+ Maia SDR firmware are called `plutoplus` instead of `plutosdr` or
`pluto`. When using the USB storage firmware update method, the file that is
copied to the USB storage device must be called `pluto.frm`. The file
`plutoplus.frm` must be renamed to `pluto.frm`.

The
[`ipaddrmulti`](https://maia-sdr.org/installation/#configure-the-pluto-usb-ethernet)
feature can conflict with the IP address assignment for the Pluto+ Ethernet. It
is probably better to disable `ipaddrmulti` in the Pluto+.

The Pluto+ firmware can be built with
```
TARGET=plutoplus make
```
