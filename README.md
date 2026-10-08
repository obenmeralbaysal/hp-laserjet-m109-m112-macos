# HP LaserJet M109-M112 on macOS

USB print driver for the HP LaserJet M111ca and the rest of the M109-M112 series.

macOS lists this printer and then drops the job. The built-in queue uses Generic PCL. This model does not speak PCL. Over USB it accepts 8-bit gray PWG raster through IPP-over-USB. This driver sends that format.

## Install

Plug the printer in with a USB cable, then:

```bash
sudo ./install.sh
```

The installer asks for an administrator password. It does three things:

- Installs the PPD in `/Library/Printers/PPDs`
- Starts a local bridge on `127.0.0.1:9101` (LaunchDaemon `com.local.hpm111`)
- Points the existing `HP_LaserJet_M109_M112` and `HP_LaserJet_M109_M112_2` queues at that bridge

The default queue is `HP_LaserJet_M109_M112_2`. Print to it from any app. Paper size defaults to A4 at 600 dpi. The printer is one-sided only.

## Printer serial

`pwg-bridge.py` finds the IPP-USB port for serial `VNC6C00025`. If your unit has a different serial, change `SERIAL` in that file before installing. The serial is the `serial=` value in:

```bash
lpstat -v
```

## Files

| File | Role |
| --- | --- |
| `HP-LaserJet-M109-M112.ppd` | CUPS PPD. Output is `image/pwg-raster`, 8-bit sGray. |
| `pwg-bridge.py` | Reads each page from the CUPS socket backend and submits it with IPP Print-Job. |
| `com.local.hpm111.plist` | LaunchDaemon that keeps the bridge running. |
| `install.sh` | Copies the files into place and retargets the queues. |

## Limits

A faint or blank page with a successful job means the toner is low. The printer reports that separately from the driver. Replug the USB cable if the bridge log says the IPP-USB port is missing; the bridge looks the port up again on the next job.
