// src/logic/core/flhash.hpp: Freelancer nickname hash (the engine's CreateID), engine-free.
//
// Same result as Common.dll's `u32 CreateID(const char*)`: a 30-bit table-driven CRC over the
// ASCII-lowercased nickname (polynomial 0xA001 shifted into the top of 30 bits), byte-swapped,
// shifted right by 2 and tagged with the top bit. Golden values are in tests/host/core/test_flhash.cpp.
#pragma once

#include <array>
#include <cstdint>
#include <string_view>

namespace flmod::logic {

namespace flhash_detail {

inline constexpr std::uint32_t kPolynomial = 0xA001u << 14;  // 0xA001 << (30 - 16)

constexpr std::array<std::uint32_t, 256> make_table() noexcept {
    std::array<std::uint32_t, 256> table{};
    for (std::uint32_t i = 0; i < 256; ++i) {
        std::uint32_t x = i;
        for (int bit = 0; bit < 8; ++bit) {
            x = (x & 1u) ? (x >> 1) ^ kPolynomial : (x >> 1);
        }
        table[i] = x;
    }
    return table;
}

inline constexpr std::array<std::uint32_t, 256> kTable = make_table();

constexpr unsigned char ascii_lower(unsigned char c) noexcept {
    return (c >= 'A' && c <= 'Z') ? static_cast<unsigned char>(c - 'A' + 'a') : c;
}

}  // namespace flhash_detail

// Compile-time capable CreateID (case-insensitive, ASCII only, like the engine).
constexpr std::uint32_t create_id_constexpr(std::string_view nickname) noexcept {
    std::uint32_t h = 0;
    for (char ch : nickname) {
        const unsigned char c = flhash_detail::ascii_lower(static_cast<unsigned char>(ch));
        h = (h >> 8) ^ flhash_detail::kTable[(h & 0xFFu) ^ c];
    }
    h = (h >> 24) | ((h >> 8) & 0x0000FF00u) | ((h << 8) & 0x00FF0000u) | (h << 24);
    return (h >> 2) | 0x80000000u;
}

// Runtime CreateID. Equal to create_id_constexpr(); kept out of line so callers don't instantiate
// the loop everywhere.
[[nodiscard]] std::uint32_t create_id(std::string_view nickname) noexcept;

}  // namespace flmod::logic
