# Connect the handheld to your computer

This guide helps your computer talk to the PS202 handheld.

You need a small program called **ADB**. You do not need Android Studio.

The installer also needs **Python 3**. Download it from
[python.org](https://www.python.org/downloads/) and accept the normal install
options. Windows users should select **Add Python to PATH** when it is shown.

## 1. Download ADB

Download **Android SDK Platform-Tools** from the official Android website:

[Download Platform-Tools](https://developer.android.com/tools/releases/platform-tools)

Choose the file for your computer:

- **Mac** — choose the Mac download
- **Linux** — choose the Linux download
- **Windows** — choose the Windows download

Unzip the download. You will get a folder named `platform-tools`.

## 2. Turn on USB debugging

On the handheld:

1. Open **Settings**.
2. Open **About device** (it may be called **About phone**).
3. Tap **Build number** seven times.
4. Go back to **Settings**.
5. Open **Developer options**.
6. Turn on **USB debugging**.

If **Developer options** is already visible, you can skip steps 2 and 3.

## 3. Connect the cable

Use a USB cable that can carry data. Some cables only charge.

Connect the handheld to the computer and turn on the handheld's screen.

If the handheld asks **Allow USB debugging?**, tap **OK**.

## 4. Check the connection

Open a command window inside the `platform-tools` folder.

### macOS or Linux

```bash
./adb devices
```

### Windows PowerShell

```powershell
.\adb.exe devices
```

### Windows Command Prompt

```bat
adb.exe devices
```

You should see one device with the word `device` next to it.

Now open the vamanOS installer folder and follow [the install guide](README.md).

If the installer says that ADB cannot be found, tell it where ADB is:

### macOS or Linux

```bash
./install.sh --adb /path/to/platform-tools/adb doctor
./install.sh --adb /path/to/platform-tools/adb install
```

### Windows PowerShell

```powershell
.\install.ps1 --adb C:\path\to\platform-tools\adb.exe doctor
.\install.ps1 --adb C:\path\to\platform-tools\adb.exe install
```

## If no device appears

Try these simple fixes:

1. Unlock the handheld and tap **OK** on the USB debugging message.
2. Try a different USB cable or USB port.
3. Close and reopen the command window.
4. On Windows, install the USB driver for the handheld. Android keeps a list
   of manufacturer drivers here:
   [Android USB drivers for Windows](https://developer.android.com/studio/run/oem-usb)

Mac and Linux normally do not need a USB driver.

If `adb devices` works in the `platform-tools` folder but the installer says
that ADB cannot be found, run the installer from a command window that can
find `adb`, or ask for help with the exact message on the screen.
