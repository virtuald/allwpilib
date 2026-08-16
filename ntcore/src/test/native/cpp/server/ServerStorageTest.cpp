// Copyright (c) FIRST and other WPILib contributors.
// Open Source Software; you can modify and/or share it under the terms of
// the WPILib BSD license file in the root directory of this project.

#include "server/ServerStorage.hpp"

#include <vector>

#include <catch2/catch_test_macros.hpp>

#include "../MockLogger.hpp"
#include "server/ServerTopic.hpp"
#include "wpi/nt/NetworkTableValue.hpp"
#include "wpi/util/json.hpp"

namespace wpi::nt::server {

TEST_CASE("ServerStorage limits aggregate persistent value bytes",
          "[ntcore][server][storage]") {
  wpi::MockLogger logger;
  ServerStorage storage{logger,
                        [](ServerTopic*, ServerClient*) {},
                        {.maxNetworkTopics = 1, .maxPersistentValueSize = 8}};
  auto properties = wpi::util::json::object("persistent", true);

  auto first = storage.CreateTopic(nullptr, "first", "raw", properties);
  auto second = storage.CreateTopic(nullptr, "second", "raw", properties);
  storage.SetValue(nullptr, first, Value::MakeRaw(std::vector<uint8_t>(6), 1));
  storage.SetValue(nullptr, second, Value::MakeRaw(std::vector<uint8_t>(6), 1));

  CHECK(first->lastValue);
  CHECK_FALSE(second->lastValue);

  storage.DeleteTopic(first);
  storage.SetValue(nullptr, second, Value::MakeRaw(std::vector<uint8_t>(6), 2));
  CHECK(second->lastValue);
}

TEST_CASE("ServerStorage limits network-created topic count",
          "[ntcore][server][storage]") {
  wpi::MockLogger logger;
  ServerStorage storage{logger,
                        [](ServerTopic*, ServerClient*) {},
                        {.maxNetworkTopics = 1, .maxPersistentValueSize = 8}};

  CHECK(storage.CanCreateNetworkTopic());
  auto topic =
      storage.CreateTopic(nullptr, "first", "double", wpi::util::json{});
  CHECK_FALSE(storage.CanCreateNetworkTopic());
  storage.DeleteTopic(topic);
  CHECK(storage.CanCreateNetworkTopic());
}

}  // namespace wpi::nt::server
