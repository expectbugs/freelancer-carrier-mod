// src/logic/core/flhash.cpp
#include "logic/core/flhash.hpp"

namespace flmod::logic {

std::uint32_t create_id(std::string_view nickname) noexcept {
    return create_id_constexpr(nickname);
}

}  // namespace flmod::logic
