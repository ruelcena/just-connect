/*
 * pybind11 wrapper around TinyVNC's Network::VncClient.
 *
 * The module is named ``_tinyvnc`` and is imported by
 * ``just_connect.tinyvnc_backend``.
 */

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "vendor/vnc_client.hpp"

namespace py = pybind11;

PYBIND11_MODULE(_tinyvnc, m)
{
    m.doc() = "TinyVNC pybind11 wrapper";

    // Initialize network sockets once when the module is loaded.
    Network::initialize();

    py::class_<Network::VncClient>(m, "VncClient")
        .def(py::init<const char*, const char*>(),
             py::arg("hostname"), py::arg("port"))
        .def("update", &Network::VncClient::update,
             "Pump the network state machine. Call repeatedly until connected.",
             py::arg("timeout") = -1.0f)
        .def("set_password", py::overload_cast<const char*>(&Network::VncClient::set_password),
             py::arg("password"))
        .def("connected", &Network::VncClient::connected)
        .def("error_code", &Network::VncClient::error_code)
        .def("error_description", &Network::VncClient::error_description)
        .def("request_screen", &Network::VncClient::request_screen,
             py::arg("incremental"), py::arg("x"), py::arg("y"),
             py::arg("width"), py::arg("height"))
        .def("set_keep_framebuffer", &Network::VncClient::set_keep_framebuffer,
             py::arg("keep"))
        .def("framebuffer_width", &Network::VncClient::framebuffer_width)
        .def("framebuffer_height", &Network::VncClient::framebuffer_height)
        .def("framebuffer_bpp", &Network::VncClient::framebuffer_bpp)
        .def("framebuffer_version", &Network::VncClient::framebuffer_version)
        .def(
            "framebuffer",
            [](const Network::VncClient& client) -> py::bytes {
                const char* data = client.framebuffer();
                int width = client.framebuffer_width();
                int height = client.framebuffer_height();
                int bpp = client.framebuffer_bpp();
                if (data == nullptr || width <= 0 || height <= 0 || bpp <= 0) {
                    return py::bytes();
                }
                std::size_t size = static_cast<std::size_t>(width * height * bpp);
                return py::bytes(data, size);
            },
            "Return the current RAW framebuffer as bytes."
        )
        .def("send_key", &Network::VncClient::send_key,
             py::arg("key"), py::arg("down"))
        .def("pulse_key", &Network::VncClient::pulse_key,
             py::arg("key"));

    // Expose the error constants used by TinyVNC.
    m.attr("STREAM_NO_ERROR") = STREAM_NO_ERROR;
    m.attr("STREAM_TCP_ERROR") = STREAM_TCP_ERROR;
    m.attr("STREAM_VNC_PROTOCOL_ERROR") = STREAM_VNC_PROTOCOL_ERROR;
    m.attr("STREAM_VNC_PASSWORD_REQUIRED") = STREAM_VNC_PASSWORD_REQUIRED;
    m.attr("STREAM_VNC_USERNAME_PASSWORD_REQUIRED") = STREAM_VNC_USERNAME_PASSWORD_REQUIRED;
    m.attr("STREAM_VNC_LOGIN_FAILED") = STREAM_VNC_LOGIN_FAILED;
    m.attr("STREAM_VNC_UNSUPPORTED") = STREAM_VNC_UNSUPPORTED;

    // Best-effort cleanup when the interpreter exits.
    auto atexit = py::module_::import("atexit");
    atexit.attr("register")(py::cpp_function([]() { Network::deinitialize(); }));
}
