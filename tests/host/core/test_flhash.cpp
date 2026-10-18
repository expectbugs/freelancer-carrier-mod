// tests/host/core/test_flhash.cpp: CreateID port, golden-tested against values the engine produced
// (R3 §10, VERIFIED against the game's own save data). Li02 is also checked in-engine by hello_b.
#include <doctest/doctest.h>

#include "logic/core/flhash.hpp"

#include <cstdint>
#include <string>

using flmod::logic::create_id;
using flmod::logic::create_id_constexpr;

TEST_CASE("create_id matches the engine's golden values") {
    struct Golden {
        const char* nickname;
        std::uint32_t id;
    };
    const Golden golden[] = {
        {"Li01_to_Li02", 2830511361u},
        {"Ew06_01_Base", 3094908802u},
        {"Li02", 2745692751u},
        {"ew0601_monkey_003_m", 2318074572u},
        {"Br05", 2945937410u},
    };
    for (const auto& g : golden) {
        CAPTURE(g.nickname);
        CHECK(create_id(g.nickname) == g.id);
    }
}

TEST_CASE("create_id is case-insensitive (ASCII)") {
    CHECK(create_id("li02") == create_id("LI02"));
    CHECK(create_id("li02") == 2745692751u);
    CHECK(create_id("ew0601_MONKEY_003_M") == 2318074572u);
}

TEST_CASE("create_id is usable at compile time and agrees with the runtime version") {
    static_assert(create_id_constexpr("Li02") == 2745692751u);
    static_assert(create_id_constexpr("Br05") == 2945937410u);
    const std::string s = "Li01_to_Li02";
    CHECK(create_id(s) == create_id_constexpr("Li01_to_Li02"));
}

TEST_CASE("create_id always sets the top bit") {
    CHECK((create_id("") & 0x80000000u) != 0);
    CHECK(create_id("") == 0x80000000u);
    CHECK((create_id("fcm_salvage_pod") & 0x80000000u) != 0);
}
