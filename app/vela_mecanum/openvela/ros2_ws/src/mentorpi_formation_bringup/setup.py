from glob import glob
from pathlib import Path

from setuptools import find_packages, setup


package_name = "mentorpi_formation_bringup"


setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml", "README.md"]),
        (f"share/{package_name}/launch", glob("launch/*.launch.py")),
        (f"share/{package_name}/config", glob("config/*.yaml")),
        (f"share/{package_name}/scripts", glob("scripts/*.sh")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    entry_points={
        "console_scripts": [
            "hardware_probe = mentorpi_formation_bringup.hardware_probe:main",
            "lidar_guarded_motion_test = mentorpi_formation_bringup.lidar_guarded_motion_test:main",
            "drive_distance = mentorpi_formation_bringup.drive_distance:main",
            "orbit_obstacle = mentorpi_formation_bringup.orbit_obstacle:main",
            "scan_symmetric = mentorpi_formation_bringup.scan_symmetric:main",
            "set_initial_pose = mentorpi_formation_bringup.set_initial_pose:main",
            "tf_audit = mentorpi_formation_bringup.tf_audit:main",
            "virtual_acceptance = mentorpi_formation_bringup.virtual_acceptance:main",
            "virtual_fleet = mentorpi_formation_bringup.virtual_fleet:main",
        ],
    },
)
