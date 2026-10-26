# Keep the extension files installed

Unzip the package into a permanent folder such as `~/Applications/Career Companion Extensions/chrome`. In Chrome, use **Load unpacked** in `chrome://extensions` and select that folder. Keep it in place; Chrome reads those files directly. A deleted folder causes `ERR_FILE_NOT_FOUND`.

For updates, replace the package files in that same folder, then choose **Reload**. A new folder may change the extension identity and require pairing again. The localhost package only connects to localhost and 127.0.0.1. It contains no account data or provider keys.
