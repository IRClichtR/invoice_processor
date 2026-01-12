import os
import structlog
import platform
import tarfile
import subprocess
import zipfile
import httpx
from pathlib import Path

logger = structlog.get_logger()

DEPENDENCIES = {
    "windows": {
        "tesseract": {
            "url": "https://github.com/ton-repo/releases/download/deps-v1/tesseract-windows-x64.zip",
            "version": "5.3.3",
            "test_cmd": ["tesseract", "--version"],
        },
    },
    "darwin": {  # macOS
        "tesseract": {
            "url": "https://github.com/ton-repo/releases/download/deps-v1/tesseract-macos-{arch}.tar.gz",
            "version": "5.3.3",
            "test_cmd": ["tesseract", "--version"],
        },
    },
    "linux": {
        "tesseract": {
            "url": "https://github.com/ton-repo/releases/download/deps-v1/tesseract-linux-x64.tar.gz",
            "version": "5.3.3",
            "test_cmd": ["tesseract", "--version"],
        },
    },
}


class DependenciesManager:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.deps_dir = self.data_dir / "dependencies"
        self.bin_dir = self.deps_dir / "bin"
        self.deps_dir.mkdir(parents=True, exist_ok=True)
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        
        # add bin to PATH for subprocess calls
        os.environ["PATH"] = str(self.bin_dir) + os.pathsep + os.environ.get("PATH", "")
        
        # define Tesseract data prefix
        tessdata_dir = self.deps_dir / "tessdata"
        if tessdata_dir.exists():
            os.environ["TESSDATA_PREFIX"] = str(tessdata_dir) + os.path.sep
        
    def get_platform(self):
        system = platform.system().lower()
        arch = platform.machine().lower()
        if system == "darwin":
            if arch == "x86_64":
                arch = "x64"
            elif arch == "arm64":
                arch = "arm64"
        return system, arch
        
    def is_installed(self):
        """Check if all dependencies are installed and work."""
        
        system = self.get_platform()
        dep_info = DEPENDENCIES.get(system[0], {}).get("tesseract")
        if not dep_info:
            logger.error(f"No dependency info for platform: {system}")
            return False
        
        try:
            # Get name of executable from test command
            test_cmd = dep_info["test_cmd"]
            exe_name = test_cmd[0]
            
            # if Windows, append .exe
            if system[0] == "windows":
                exe_name += ".exe"
            
            exe_path = self.bin_dir / exe_name
            if not exe_path.exists():
                logger.info(f"Dependency {exe_name} not found at {exe_path}")
                return False
            else:
                result = subprocess.run(
                    [str(exe_path)] + test_cmd[1:],
                    capture_output = True,
                    timeout=10
                )
                return result.returncode == 0
            # Fallback mechanism: try running the test command directly
            result = subprocess.run(
                test_cmd,
                capture_output=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Error checking dependency {dep_info}: {e}")
            return False

    def download_and_install(self):
        """Download and install dependencies."""
        
        system = self.get_platform()
        dep_info = DEPENDENCIES.get(system[0], {}).get("tesseract")
        if not dep_info:
            logger.error(f"No dependency info for platform: {system}")
            return
        
        url = dep_info["url"].format(arch=system[1])
        logger.info(f"Downloading dependency from {url}...")
        
        try:
            response = httpx.get(url, timeout=60.0)
            response.raise_for_status()
            
            archive_path = self.deps_dir / "dependency_archive"
            with open(archive_path, "wb") as f:
                f.write(response.content)
            
            logger.info(f"Extracting dependency archive...")
            if url.endswith(".zip"):
                with zipfile.ZipFile(archive_path, "r") as zip_ref:
                    zip_ref.extractall(self.bin_dir)
            elif url.endswith(".tar.gz") or url.endswith(".tgz"):
                with tarfile.open(archive_path, "r:gz") as tar_ref:
                    tar_ref.extractall(self.bin_dir)
            else:
                logger.error(f"Unsupported archive format for URL: {url}")
                return
            
            os.remove(archive_path)
            logger.info(f"Dependency installed successfully.")
        except Exception as e:
            logger.error(f"Error downloading/installing dependency from {url}: {e}")
            
    def _is_executable(self, file_path: Path) -> bool:
        """Check if a file is executable."""
        return os.access(file_path, os.X_OK)
        
    def ensure_dependencies(self):
        """Ensure all dependencies are installed."""
        if not self.is_installed():
            logger.info("Dependencies not found or not working. Installing...")
            self.download_and_install()
            if self.is_installed():
                logger.info("All dependencies installed and working.")
            else:
                logger.error("Failed to install dependencies.")
        else:
            logger.info("All dependencies are already installed and working.")