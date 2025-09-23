import argparse
import os
import sys
import platform
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

def onerror(func, path, exc_info):
    """
    Error handler for ``shutil.rmtree``.

    If the error is due to an access error (read only file)
    it attempts to add write permission and then retries.

    If the error is for another reason it re-raises the error.

    Usage : ``shutil.rmtree(path, onerror=onerror)``
    """
    import stat
    # Is the error an access error?
    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR)
        func(path)
    else:
        raise

def yeetdir(path):
    os.makedirs(path, exist_ok=True)
    shutil.rmtree(path, onerror=onerror)

@contextmanager
def pushd(new_dir):
    previous_dir = os.getcwd()
    os.chdir(new_dir)
    try:
        yield
    finally:
        os.chdir(previous_dir)

def fixup_line_endings(file_path):
    file_data = ""

    with open(file_path, 'rb') as file:
        file_data = file.read()

    file_data = file_data.replace(b'\r\n',  b'\n')

    with open(file_path, 'wb') as file:
        file.write(file_data)

##### main:

parser = argparse.ArgumentParser()
parser.add_argument("--config", default="release", help="compile in debug config (default is release)")
argv = sys.argv[1:]
args = parser.parse_args(argv)

ANGLE_COMMIT = ""
with open("commit.txt", "r") as f:
    ANGLE_COMMIT = f.read().strip()

if ANGLE_COMMIT == "":
	print("Failed to find commit.txt")
	exit(1)

input_config = args.config
config = input_config.lower()
if config != "release" and config != "debug":
	print("Invalid configuration " + config + ", only 'release' or 'debug' allowed")
	exit(1)

print("Building angle at sha " + ANGLE_COMMIT + " in config: " + config)

os.makedirs("build", exist_ok=True)

with pushd("build"):
    # get depot tools repo
    print("  * checking depot tools")
    if not os.path.exists("depot_tools"):
        subprocess.run([
            "git", "clone", "--depth=1", "--no-tags", "--single-branch",
            "https://chromium.googlesource.com/chromium/tools/depot_tools.git"
        ], check=True)
    os.environ["PATH"] = os.path.join(os.getcwd(), "depot_tools") + os.pathsep + os.environ["PATH"]
    os.environ["DEPOT_TOOLS_WIN_TOOLCHAIN"] = "0"

    # get angle repo
    print("  * checking angle")
    if not os.path.exists("angle"):
        subprocess.run([
            "git", "clone", "--no-tags", "--single-branch",
            "https://chromium.googlesource.com/angle/angle"
        ], check=True)

    with pushd("angle"):
        subprocess.run([
            "git", "fetch", "--no-tags"
        ], check=True)

        subprocess.run([
            "git", "reset", "--hard", ANGLE_COMMIT
        ], check=True)

        subprocess.run([
            sys.executable, "scripts/bootstrap.py"
        ], check=True)

        shell = True if platform.system() == "Windows" else False
        subprocess.run(["gclient", "sync"], shell=shell, check=True)

        print("  * preparing build")

        is_debug = "false" if config == "release" else "true"

        gnargs = [
            "angle_build_all=false",
            "angle_build_tests=false",
            f"is_debug={is_debug}",
            "is_component_build=false",
        ]

        if platform.system() == "Windows":
            gnargs += [
                "angle_enable_d3d9=false",
                "angle_enable_gl=false",
                "angle_enable_vulkan=false",
                "angle_enable_null=false",
                "angle_has_frame_capture=false"
            ]
        elif platform.system() == "Darwin":
            gnargs += [
                #NOTE(martin): oddly enough, this is needed to avoid deprecation errors when _not_ using OpenGL,
                #              because angle uses some CGL APIs to detect GPUs.
                "treat_warnings_as_errors=false",
                "angle_enable_metal=true",
                "angle_enable_gl=false",
                "angle_enable_vulkan=false",
                "angle_enable_null=false"
            ]
        elif platform.system() == "Linux":
            gnargs += [
                "angle_enable_gl=false",
                "angle_enable_vulkan=true",
                "angle_enable_null=false"
            ]
        else:
            assert False, "Unsupported OS"

        gnargString = ' '.join(gnargs)

        subprocess.run(["gn", "gen", f"out/{config}", f"--args={gnargString}"], shell=shell, check=True)

        print("  * building")
        subprocess.run(["autoninja", "-C", f"out/{config}", "libEGL", "libGLESv2"], shell=shell, check=True)

    # on macOS, change install name to executable path
    if platform.system() == "Darwin":
        subprocess.run(['install_name_tool', '-id', '@executable_path/libEGL.dylib', f'angle/out/{config}/libEGL.dylib'], check=True)
        subprocess.run(['install_name_tool', '-id', '@executable_path/libGLESv2.dylib', f'angle/out/{config}/libGLESv2.dylib'], check=True)

    # package result
    print("  * copying build artifacts...")

    yeetdir("angle.out")
    os.makedirs("angle.out/include/KHR", exist_ok=True)
    os.makedirs("angle.out/include/EGL", exist_ok=True)
    os.makedirs("angle.out/include/GLES", exist_ok=True)
    os.makedirs("angle.out/include/GLES2", exist_ok=True)
    os.makedirs("angle.out/include/GLES3", exist_ok=True)
    os.makedirs("angle.out/lib", exist_ok=True)

    # - includes
    # these are explicitly listed to avoid copying non-header files
    shutil.copy(f"angle/include/KHR/khrplatform.h", "angle.out/include/KHR/")

    shutil.copy(f"angle/include/EGL/egl.h", "angle.out/include/EGL/")
    shutil.copy(f"angle/include/EGL/eglext.h", "angle.out/include/EGL/")
    shutil.copy(f"angle/include/EGL/eglext_angle.h", "angle.out/include/EGL/")
    shutil.copy(f"angle/include/EGL/eglplatform.h", "angle.out/include/EGL/")

    shutil.copy(f"angle/include/GLES/egl.h", "angle.out/include/GLES/")
    shutil.copy(f"angle/include/GLES/gl.h", "angle.out/include/GLES/")
    shutil.copy(f"angle/include/GLES/glext.h", "angle.out/include/GLES/")
    shutil.copy(f"angle/include/GLES/glplatform.h", "angle.out/include/GLES/")

    shutil.copy(f"angle/include/GLES2/gl2.h", "angle.out/include/GLES2/")
    shutil.copy(f"angle/include/GLES2/gl2ext.h", "angle.out/include/GLES2/")
    shutil.copy(f"angle/include/GLES2/gl2ext_angle.h", "angle.out/include/GLES2/")
    shutil.copy(f"angle/include/GLES2/gl2platform.h", "angle.out/include/GLES2/")

    shutil.copy(f"angle/include/GLES3/gl3.h", "angle.out/include/GLES3/")
    shutil.copy(f"angle/include/GLES3/gl31.h", "angle.out/include/GLES3/")
    shutil.copy(f"angle/include/GLES3/gl32.h", "angle.out/include/GLES3/")
    shutil.copy(f"angle/include/GLES3/gl3platform.h", "angle.out/include/GLES3/")

    # - libs
    if platform.system() == "Windows":
        shutil.copy(f"angle/out/{config}/libEGL.dll", "angle.out/lib/")
        shutil.copy(f"angle/out/{config}/libGLESv2.dll", "angle.out/lib/")

        shutil.copy(f"angle/out/{config}/libEGL.dll.lib", "angle.out/lib/")
        shutil.copy(f"angle/out/{config}/libGLESv2.dll.lib", "angle.out/lib/")

        subprocess.run(["copy", "/y",
                        "%ProgramFiles(x86)%\\Windows Kits\\10\\Redist\\D3D\\x64\\d3dcompiler_47.dll",
                        "angle.out\\lib\\"], shell=True, check=True)
    elif platform.system() == "Darwin":
        shutil.copy(f"angle/out/{config}/libEGL.dylib", "angle.out/lib")
        shutil.copy(f"angle/out/{config}/libGLESv2.dylib", "angle.out/lib")
    elif platform.system() == "Linux":
        shutil.copy(f"angle/out/{config}/libEGL.so", "angle.out/lib")
        shutil.copy(f"angle/out/{config}/libGLESv2.so", "angle.out/lib")
    else:
        assert False, "Unsupported OS"

    # ensure line endings are consistent between windows/unix systems since they
    # will be used in the Orca project
    pathlist = Path("angle.out/include").glob('**/*.h')
    for path in pathlist:
        fixup_line_endings(str(path))
