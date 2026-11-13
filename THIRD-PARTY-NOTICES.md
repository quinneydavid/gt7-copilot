# Third-party notices

GT7 Copilot's own code is under the MIT licence ([LICENSE](LICENSE)). This file lists what comes from elsewhere: the data files in the repository, and what the container image downloads when it is built.

## Data in the repository

### Track outlines: `data/circuits.json`

Built by `tools/build_circuits.py` from the circuit inventory of [zetetos/gt-telemetry](https://github.com/zetetos/gt-telemetry) (`pkg/circuits/inventory`). Names, lengths and the grid cells each layout passes through are taken; the cells are stored in a smaller form. Licence of the source, MIT:

    MIT License

    Copyright (c) 2024 vwhitteron

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

### Car and maker names, stock performance points: `data/cars.csv`, `data/maker.csv`, `data/stockpp.csv`

From [ddm999/gt7info](https://github.com/ddm999/gt7info) (`_data/db`), fetched by `tools/refresh_carspecs.py`. Licence of the source, MIT No Attribution:

    MIT No Attribution

    Copyright 2022 Daniel Lee / @ddm999

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

### Car specifications: `data/carspecs.csv`

Collected from the public car list on gran-turismo.com by `tools/refresh_carspecs.py`. The file holds car names and specification figures (facts) from gran-turismo.com: drivetrain, aspiration, power, torque, weight, performance points and class. No text, pictures or other material from the site are included. Gran Turismo is a trademark of Sony Interactive Entertainment Inc. / Polyphony Digital; this project is not affiliated with either.

### Tuning datapoints: `data/knowledge.json`

Short statements in this project's own words, each with the title and link of the guide it is based on.

## What the copilot image contains

The image `gt7-copilot` is built from the `Dockerfile`. Besides this project it contains the following, each under its own licence. The licence texts of the Python packages are in their folders under `site-packages` in the image.

| What | From | Licence |
|---|---|---|
| Base image | `python:3.13-slim` (Debian, CPython) | PSF licence for Python; Debian packages under their own licences (`/usr/share/doc/*/copyright` in the image) |
| Kokoro voice model: `kokoro-v1.0.onnx`, `voices-v1.0.bin` | [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), as packaged in the [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) releases; downloaded at build time, pinned by checksum | Apache-2.0 |
| kokoro-onnx | [thewh1teagle/kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) | MIT |
| phonemizer (installed by kokoro-onnx) | [bootphon/phonemizer](https://github.com/bootphon/phonemizer) | GPL-3.0 |
| espeakng-loader with the eSpeak NG library and its data (installed by kokoro-onnx) | [thewh1teagle/espeakng-loader](https://github.com/thewh1teagle/espeakng-loader), [espeak-ng/espeak-ng](https://github.com/espeak-ng/espeak-ng) | eSpeak NG: GPL-3.0-or-later |
| ONNX Runtime | [microsoft/onnxruntime](https://github.com/microsoft/onnxruntime) | MIT |
| NumPy | [numpy/numpy](https://github.com/numpy/numpy) | BSD-3-Clause, with bundled parts under their own licences |
| soundfile, with the libsndfile library | [bastibe/python-soundfile](https://github.com/bastibe/python-soundfile), [libsndfile](https://github.com/libsndfile/libsndfile) | BSD-3-Clause; libsndfile LGPL-2.1-or-later |
| PyCryptodome | [Legrandin/pycryptodome](https://github.com/Legrandin/pycryptodome) | BSD-2-Clause and public domain |

The packages are installed unchanged from PyPI at the versions in `requirements.txt`; further packages they pull in are under their own licences. phonemizer and eSpeak NG are under the GPL: this project's code does not include them or link them into its own files. They are separate packages in the image, used by kokoro-onnx to turn text into phonemes. Their source is at the links above. Anyone who passes the image on passes those packages on with it and has to keep to their licences.

## The phone image

The image `gt7-copilot-phone` is Ubuntu with packages from Ubuntu's archive (among them OpenJDK, Xvfb, x11vnc, noVNC, websockify, openbox, xdotool), each under its own licence (`/usr/share/doc/*/copyright` in the image). The Android SDK, the emulator and the system image are not in it: they are downloaded from Google on first start, under Google's terms, once `ANDROID_LICENSES=accept` is set (docs/phone.md). The PlayStation App is installed by the user from Google Play.

## Not bundled

The `voice` profile of the compose file runs the image `ghcr.io/speaches-ai/speaches`, which is pulled from its own registry and is not part of this project.
