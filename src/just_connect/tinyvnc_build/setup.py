"""Setuptools driver for the optional TinyVNC pybind11 backend.

Run from the project root:

    pip install .[tinyvnc]

or, to build only the extension:

    python src/just_connect/tinyvnc_build/setup.py build_ext --inplace
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup


HERE = Path(__file__).resolve().parent
VENDOR = HERE / "vendor"


def _collect_cryptopp_sources() -> list[str]:
    sources = sorted(str(p) for p in VENDOR.glob("cryptoppmin/*.cpp"))
    exclude = {"ec2n.cpp", "eccrypto.cpp", "eprecomp.cpp", "strciphr.cpp"}
    return [s for s in sources if Path(s).name not in exclude]


ext_modules = [
    Pybind11Extension(
        "just_connect._tinyvnc",
        sources=[
            str(HERE / "tinyvnc_binding.cpp"),
            str(VENDOR / "raw_query.cpp"),
            str(VENDOR / "vnc_client.cpp"),
            str(VENDOR / "des_local.cpp"),
            *_collect_cryptopp_sources(),
        ],
        include_dirs=[str(VENDOR)],
        cxx_std=17,
        # Match the CMake defines requested by the user.
        define_macros=[
            ("CRYPTOPP_DISABLE_ASM", "1"),
            ("CRYPTOPP_MANUALLY_INSTANTIATE_TEMPLATES", "1"),
            ("WIN32", "1") if os.name == "nt" else ("", ""),
        ],
        libraries=["ws2_32"] if os.name == "nt" else [],
    )
]


class CMakeBuildExt(build_ext):
    """Fallback build that uses CMake when the setuptools path is not used."""

    def run(self) -> None:
        if shutil.which("cmake") is None:
            raise RuntimeError(
                "CMake is required to build the TinyVNC backend but was not found. "
                "Install CMake or use the pure-Python vncdotool backend instead."
            )
        build_temp = Path(self.build_temp)
        build_temp.mkdir(parents=True, exist_ok=True)
        cfg = "Debug" if self.debug else "Release"
        subprocess.run(
            ["cmake", "-S", str(HERE), "-B", str(build_temp), f"-DCMAKE_BUILD_TYPE={cfg}"],
            check=True,
        )
        subprocess.run(
            ["cmake", "--build", str(build_temp), "--config", cfg],
            check=True,
        )
        # Copy the compiled extension next to the Python package.
        ext_path = Path(self.get_ext_fullpath("just_connect._tinyvnc"))
        ext_path.parent.mkdir(parents=True, exist_ok=True)
        candidates = list(build_temp.glob(f"**/*_tinyvnc*{sysconfig.get_config_var('EXT_SUFFIX')}"))
        if not candidates:
            raise RuntimeError("Could not find compiled _tinyvnc extension")
        shutil.copy2(candidates[0], ext_path)


setup(
    name="just-connect-tinyvnc",
    version="0.1.0",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
)
