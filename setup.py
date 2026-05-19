from setuptools import setup
from pybind11.setup_helpers import Pybind11Extension, build_ext
ext_modules = [
    Pybind11Extension(
        "graph_native",
        ["native/graph_module.cpp", "native/graph_core.cpp"],
        include_dirs=["native"],
        cxx_std=17,
    ),
]
setup(
    name="graph_native",
    version="0.1.0",
    author="rejuive",
    description="Native C++ graph processing module",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
    python_requires=">=3.7",
)