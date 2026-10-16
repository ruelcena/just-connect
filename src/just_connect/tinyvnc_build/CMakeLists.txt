cmake_minimum_required(VERSION 3.15)
project(tinyvnc_binding)

# Locate pybind11. It may be installed in the active Python environment.
find_package(pybind11 REQUIRED)

# TinyVNC ships with a bundled, stripped-down Crypto++ in vendor/cryptoppmin.
# The upstream project asks for these two defines when building on toolchains
# that lack assembler support, and excludes a handful of Crypto++ source files
# that are not needed for VNC authentication.
add_compile_definitions(
    CRYPTOPP_DISABLE_ASM
    CRYPTOPP_MANUALLY_INSTANTIATE_TEMPLATES
)

if(WIN32)
    add_compile_definitions(WIN32 _WIN32)
    link_libraries(ws2_32)
endif()

# Collect the TinyVNC core sources.
set(TINYVNC_SOURCES
    vendor/raw_query.cpp
    vendor/vnc_client.cpp
    vendor/des_local.cpp
)

# Collect Crypto++ sources, excluding the files TinyVNC omits.
file(GLOB CRYPTOPP_SOURCES vendor/cryptoppmin/*.cpp)
set(CRYPTOPP_EXCLUDE
    vendor/cryptoppmin/ec2n.cpp
    vendor/cryptoppmin/eccrypto.cpp
    vendor/cryptoppmin/eprecomp.cpp
    vendor/cryptoppmin/strciphr.cpp
)
foreach(exclude_file ${CRYPTOPP_EXCLUDE})
    list(REMOVE_ITEM CRYPTOPP_SOURCES ${exclude_file})
endforeach()

# Some Crypto++ headers are self-contained templates; the object files above
# are enough for the DES/VNC-auth and ARD-auth code paths used by TinyVNC.
pybind11_add_module(_tinyvnc
    tinyvnc_binding.cpp
    ${TINYVNC_SOURCES}
    ${CRYPTOPP_SOURCES}
)

# tinyvnc_binding.cpp includes vendor/vnc_client.hpp, so add the vendor dir.
target_include_directories(_tinyvnc PRIVATE vendor)

# On Windows the socket library is linked above; on Unix no extra link is needed.
if(NOT WIN32)
    target_compile_options(_tinyvnc PRIVATE -Wno-deprecated-declarations)
endif()
