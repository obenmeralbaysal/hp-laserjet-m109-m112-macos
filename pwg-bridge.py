#!/usr/bin/python3
"""Accept raw PWG Raster from the CUPS socket backend and submit it over IPP-USB.

The HP LaserJet M109-M112 / M111ca prints image/pwg-raster (8-bit sGray).
macOS will not run a custom CUPS backend, so CUPS talks to 127.0.0.1:9101
and this process forwards each job to the printer's IPP-USB port.
"""

import os
import re
import socket
import subprocess
import tempfile
import time

HOST = "127.0.0.1"
PORT = 9101
IPPTOOL = "/usr/bin/ipptool"
SERIAL = "VNC6C00025"
LOG_PATH = "/Library/Printers/HPM111/bridge.log"

MEDIA_BY_POINTS = {
    (595, 842): "iso_a4_210x297mm",
    (612, 792): "na_letter_8.5x11in",
    (612, 1008): "na_legal_8.5x14in",
    (420, 595): "iso_a5_148x210mm",
    (298, 420): "iso_a6_105x148mm",
    (288, 432): "na_index-4x6_4x6in",
    (360, 504): "na_5x7_5x7in",
    (312, 624): "iso_dl_110x220mm",
    (297, 684): "na_number-10_4.125x9.5in",
    (459, 649): "iso_c5_162x229mm",
    (323, 459): "iso_c6_114x162mm",
}


def log(message):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n"
    try:
        with open(LOG_PATH, "a") as handle:
            handle.write(line)
    except OSError:
        pass
    sys_stderr(line)


def sys_stderr(line):
    try:
        import sys
        sys.stderr.write(line)
        sys.stderr.flush()
    except Exception:
        pass


def ippusb_port():
    listed = subprocess.check_output(["/bin/launchctl", "list"], text=True, stderr=subprocess.DEVNULL)
    label = ""
    for line in listed.splitlines():
        if "ippusb" not in line or SERIAL not in line:
            continue
        fields = line.split("\t")
        if len(fields) >= 3:
            label = fields[2].strip()
        else:
            parts = line.split(None, 2)
            label = parts[2].strip() if len(parts) == 3 else ""
        if label:
            break
    if not label:
        label = "com.apple.print.ippusb.HP.HP LaserJet M109-M112.%s" % SERIAL
    info = subprocess.check_output(
        ["/bin/launchctl", "print", "system/" + label],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    match = re.search(r"service name = (\d+)", info)
    if not match:
        raise RuntimeError("IPP-USB port not found for %s" % SERIAL)
    return match.group(1)


def page_ticket(data):
    media = "iso_a4_210x297mm"
    resolution = "600dpi"
    if not data.startswith(b"RaS2"):
        return media, resolution
    try:
        import ctypes
        lib = ctypes.cdll.LoadLibrary("/usr/lib/libcups.2.dylib")

        class Header(ctypes.Structure):
            _fields_ = [
                ("MediaClass", ctypes.c_char * 64),
                ("MediaColor", ctypes.c_char * 64),
                ("MediaType", ctypes.c_char * 64),
                ("OutputType", ctypes.c_char * 64),
                ("AdvanceDistance", ctypes.c_uint),
                ("AdvanceMedia", ctypes.c_int),
                ("Collate", ctypes.c_int),
                ("CutMedia", ctypes.c_int),
                ("Duplex", ctypes.c_int),
                ("HWResolution", ctypes.c_uint * 2),
                ("ImagingBoundingBox", ctypes.c_uint * 4),
                ("InsertSheet", ctypes.c_int),
                ("Jog", ctypes.c_int),
                ("LeadingEdge", ctypes.c_int),
                ("Margins", ctypes.c_uint * 2),
                ("ManualFeed", ctypes.c_int),
                ("MediaPosition", ctypes.c_uint),
                ("MediaWeight", ctypes.c_uint),
                ("MirrorPrint", ctypes.c_int),
                ("NegativePrint", ctypes.c_int),
                ("NumCopies", ctypes.c_uint),
                ("Orientation", ctypes.c_int),
                ("OutputFaceUp", ctypes.c_int),
                ("PageSize", ctypes.c_uint * 2),
                ("Separations", ctypes.c_int),
                ("TraySwitch", ctypes.c_int),
                ("Tumble", ctypes.c_int),
                ("cupsWidth", ctypes.c_uint),
                ("cupsHeight", ctypes.c_uint),
                ("cupsMediaType", ctypes.c_uint),
                ("cupsBitsPerColor", ctypes.c_uint),
                ("cupsBitsPerPixel", ctypes.c_uint),
                ("cupsBytesPerLine", ctypes.c_uint),
                ("cupsColorOrder", ctypes.c_int),
                ("cupsColorSpace", ctypes.c_int),
            ]

        lib.cupsRasterOpen.restype = ctypes.c_void_p
        lib.cupsRasterOpen.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.cupsRasterReadHeader2.restype = ctypes.c_uint
        lib.cupsRasterReadHeader2.argtypes = [ctypes.c_void_p, ctypes.POINTER(Header)]
        fd, path = tempfile.mkstemp(prefix="hpm111-hdr-", suffix=".pwg")
        os.write(fd, data)
        os.lseek(fd, 0, os.SEEK_SET)
        raster = lib.cupsRasterOpen(fd, 0)
        header = Header()
        if lib.cupsRasterReadHeader2(raster, ctypes.byref(header)):
            page = (int(header.PageSize[0]), int(header.PageSize[1]))
            media = MEDIA_BY_POINTS.get(page, media)
            dpi = int(header.HWResolution[0]) or 600
            if dpi not in (300, 600):
                dpi = 600
            resolution = "%ddpi" % dpi
            log("page %sx%s %s space=%s bits=%s" % (
                page[0], page[1], resolution, header.cupsColorSpace, header.cupsBitsPerColor))
        os.close(fd)
        os.unlink(path)
    except Exception as exc:
        log("header parse failed: %s" % exc)
    return media, resolution


def submit(data):
    if not data.startswith(b"RaS2"):
        raise RuntimeError("job is not PWG Raster (magic %r)" % data[:8])
    media, resolution = page_ticket(data)
    port = ippusb_port()
    uri = "ipp://127.0.0.1:%s/ipp/print" % port
    fd, path = tempfile.mkstemp(prefix="hpm111-", suffix=".pwg")
    os.write(fd, data)
    os.close(fd)
    test_fd, test_path = tempfile.mkstemp(prefix="hpm111-", suffix=".test")
    test = (
        "{\n"
        'NAME "Print"\n'
        "OPERATION Print-Job\n"
        "GROUP operation-attributes-tag\n"
        "ATTR charset attributes-charset utf-8\n"
        "ATTR language attributes-natural-language en\n"
        "ATTR uri printer-uri $uri\n"
        "ATTR name requesting-user-name $user\n"
        "ATTR mimeMediaType document-format image/pwg-raster\n"
        "ATTR name job-name CUPS\n"
        "GROUP job-attributes-tag\n"
        "ATTR integer copies 1\n"
        "ATTR keyword media %s\n"
        "ATTR keyword print-color-mode monochrome\n"
        "ATTR resolution printer-resolution %s\n"
        "ATTR keyword sides one-sided\n"
        "FILE %s\n"
        "STATUS successful-ok\n"
        "STATUS successful-ok-ignored-or-substituted-attributes\n"
        "EXPECT job-id OF-TYPE integer\n"
        "}\n" % (media, resolution, path)
    )
    os.write(test_fd, test.encode())
    os.close(test_fd)
    try:
        proc = subprocess.run(
            [IPPTOOL, "-tv", uri, test_path],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stdout.strip() or "ipptool failed")
        match = re.search(r"job-id \(integer\) = (\d+)", proc.stdout)
        if not match:
            raise RuntimeError("no job id: %s" % proc.stdout[-400:])
        job_id = match.group(1)
        log("submitted printer job %s to %s (%s %s, %d bytes)" % (job_id, uri, media, resolution, len(data)))
        wait_job(uri, job_id)
    finally:
        os.unlink(path)
        os.unlink(test_path)


def wait_job(uri, job_id):
    fd, path = tempfile.mkstemp(prefix="hpm111-job-", suffix=".test")
    test = (
        "{\n"
        'NAME "Job"\n'
        "OPERATION Get-Job-Attributes\n"
        "GROUP operation-attributes-tag\n"
        "ATTR charset attributes-charset utf-8\n"
        "ATTR language attributes-natural-language en\n"
        "ATTR uri printer-uri $uri\n"
        "ATTR integer job-id %s\n"
        "ATTR name requesting-user-name $user\n"
        "}\n" % job_id
    )
    os.write(fd, test.encode())
    os.close(fd)
    try:
        for _ in range(90):
            proc = subprocess.run(
                [IPPTOOL, "-tv", uri, path],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            state = ""
            reasons = ""
            for line in proc.stdout.splitlines():
                if "job-state (enum)" in line and "=" in line:
                    state = line.split("=", 1)[1].strip()
                elif "job-state-reasons" in line and "=" in line:
                    reasons = line.split("=", 1)[1].strip()
            log("job %s %s %s" % (job_id, state, reasons))
            if state == "completed":
                return
            if state in ("aborted", "canceled"):
                raise RuntimeError("printer %s the job (%s)" % (state, reasons))
            time.sleep(2)
        raise RuntimeError("timed out waiting for printer job %s" % job_id)
    finally:
        os.unlink(path)


def serve():
    log("listening on %s:%d" % (HOST, PORT))
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(2)
    while True:
        conn, _addr = server.accept()
        chunks = []
        try:
            while True:
                block = conn.recv(1024 * 256)
                if not block:
                    break
                chunks.append(block)
        finally:
            conn.close()
        data = b"".join(chunks)
        if len(data) < 1800 or not data.startswith(b"RaS2"):
            log("ignored %d bytes magic=%r" % (len(data), data[:8]))
            continue
        try:
            submit(data)
        except Exception as exc:
            log("job failed: %s" % exc)


if __name__ == "__main__":
    serve()
