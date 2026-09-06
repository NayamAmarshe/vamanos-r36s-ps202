#!/system/bin/sh

# This is a fixed ES tool. EmulationStation invokes the service directly when
# this filename is selected; the am fallback also lets the installed script
# be run from an Android shell.
PACKAGE=com.ps202.nayamamarshe.emulationstation
SERVICE=$PACKAGE/.PS202FtpService
ACTION=$PACKAGE.action.TOGGLE_FTP

case "$1" in
  stop) ACTION=$PACKAGE.action.STOP_FTP ;;
esac

am startservice -n "$SERVICE" -a "$ACTION" >/dev/null 2>&1
exit $?
