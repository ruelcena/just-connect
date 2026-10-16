"""Tests for connect codes and LAN discovery."""

from __future__ import annotations

import socket

from just_connect.discovery import (
    DiscoveryAnnouncer,
    build_announcement,
    find_server,
    generate_code,
    is_valid_code,
    normalize_code,
    parse_announcement,
)


def _free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_generate_code_format() -> None:
    code = generate_code()
    assert len(code) == 9
    assert code[4] == "-"
    assert is_valid_code(code)


def test_generate_code_is_random() -> None:
    assert generate_code() != generate_code()


def test_normalize_code_accepts_messy_input() -> None:
    assert normalize_code("abcd-efgh") == "ABCDEFGH"
    assert normalize_code("ABCD EFGH") == "ABCDEFGH"
    # Ambiguous characters (0/O, 1/I/L) are dropped.
    assert not is_valid_code("ABCD-EF01")


def test_announcement_roundtrip_with_matching_code() -> None:
    code = generate_code()
    data = build_announcement(code, server_port=5901, name="test-host")
    info = parse_announcement(data, code, "192.168.1.10")
    assert info is not None
    assert info.host == "192.168.1.10"
    assert info.port == 5901
    assert info.name == "test-host"


def test_announcement_rejected_with_wrong_code() -> None:
    data = build_announcement(generate_code(), server_port=5901, name="test-host")
    assert parse_announcement(data, generate_code(), "192.168.1.10") is None


def test_announcement_rejected_when_tampered() -> None:
    code = generate_code()
    data = bytearray(build_announcement(code, server_port=5901, name="test-host"))
    # Flip a byte inside the JSON body.
    data[20] ^= 0x01
    assert parse_announcement(bytes(data), code, "192.168.1.10") is None


def test_announcement_rejected_when_garbage() -> None:
    assert parse_announcement(b"not json at all", generate_code(), "1.2.3.4") is None


def test_announcement_uses_fresh_nonce_each_time() -> None:
    code = generate_code()
    first = build_announcement(code, server_port=5901, name="test-host")
    second = build_announcement(code, server_port=5901, name="test-host")
    assert first != second
    # Both still validate.
    assert parse_announcement(first, code, "h") is not None
    assert parse_announcement(second, code, "h") is not None


def test_find_server_discovers_announcer() -> None:
    discovery_port = _free_udp_port()
    code = generate_code()
    announcer = DiscoveryAnnouncer(
        code,
        server_port=5901,
        name="test-host",
        discovery_port=discovery_port,
        broadcast_addr="127.0.0.1",
        interval=0.1,
    )
    announcer.start()
    try:
        info = find_server(code, timeout=5.0, discovery_port=discovery_port)
    finally:
        announcer.stop()
    assert info is not None
    assert info.host == "127.0.0.1"
    assert info.port == 5901
    assert info.name == "test-host"


def test_find_server_ignores_other_codes() -> None:
    discovery_port = _free_udp_port()
    announcer = DiscoveryAnnouncer(
        generate_code(),
        server_port=5901,
        discovery_port=discovery_port,
        broadcast_addr="127.0.0.1",
        interval=0.1,
    )
    announcer.start()
    try:
        info = find_server(generate_code(), timeout=1.0, discovery_port=discovery_port)
    finally:
        announcer.stop()
    assert info is None
