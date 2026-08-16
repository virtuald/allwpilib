// Copyright (c) FIRST and other WPILib contributors.
// Open Source Software; you can modify and/or share it under the terms of
// the WPILib BSD license file in the root directory of this project.

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <catch2/catch_test_macros.hpp>

#define private public
#include "wpi/net/MulticastServiceResolver.hpp"
#undef private

#include "MulticastHandleManager.hpp"

TEST_CASE("C API resolver TXT pointer alignment",
          "[multicast][service-discovery]") {
  auto handle = WPI_CreateMulticastServiceResolver("_alignment._tcp");
  auto& manager = wpi::net::GetMulticastManager();
  {
    std::scoped_lock lock{manager.mutex};
    auto& data = manager.resolvers[handle]->queue.emplace_back();
    data.hostName = "h";
    data.serviceName = "s";
    data.txt.emplace_back("key", "value");
  }

  int32_t count = 0;
  WPI_ServiceData* result = WPI_GetMulticastServiceResolverData(handle, &count);
  REQUIRE(result != nullptr);
  CHECK(reinterpret_cast<uintptr_t>(result[0].txtKeys) % alignof(char*) == 0);
  CHECK(reinterpret_cast<uintptr_t>(result[0].txtValues) % alignof(char*) == 0);

  WPI_FreeServiceData(result, 1);
  WPI_FreeMulticastServiceResolver(handle);
}
