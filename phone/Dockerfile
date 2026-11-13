# The virtual Android phone: the Android emulator (hardware accelerated through /dev/kvm) with its screen served to a
# browser over noVNC. The SDK, the phone and its data live in the /data volume, so the image holds only the tooling.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl unzip openjdk-17-jre-headless xvfb x11vnc novnc websockify openbox xdotool \
      libgl1 libpulse0 libnss3 libnspr4 libxcomposite1 libxcursor1 libxi6 libxtst6 libxkbfile1 libx11-xcb1 libxcb-cursor0 \
      libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 \
      libxcb-xinerama0 libxcb-xfixes0 libdbus-1-3 libasound2t64 libxdamage1 libxrandr2 libdrm2 libgbm1 libfontconfig1 \
      libsm6 libice6 libxext6 libxrender1 fonts-dejavu-core procps \
    && rm -rf /var/lib/apt/lists/*
COPY entrypoint.sh /entrypoint.sh
# the bare address opens the phone, fitted to the browser window, reconnecting by itself
COPY index.html /usr/share/novnc/index.html
# fetches PS5 captures out of the PlayStation App for the copilot (port 6081, token GRAB_TOKEN)
COPY grabber.py /grabber.py
RUN chmod 755 /entrypoint.sh
ENV ANDROID_SDK_ROOT=/data/sdk ANDROID_AVD_HOME=/data/avd HOME=/data/home DISPLAY=:0 \
    IMAGE_PKG="system-images;android-36;google_apis_playstore;x86_64" CLT_ZIP=commandlinetools-linux-16111833_latest.zip
EXPOSE 6080 6081
ENTRYPOINT ["/entrypoint.sh"]
