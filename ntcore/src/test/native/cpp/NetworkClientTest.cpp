// Copyright (c) FIRST and other WPILib contributors.
// Open Source Software; you can modify and/or share it under the terms of
// the WPILib BSD license file in the root directory of this project.

#include "NetworkClient.hpp"

#include <atomic>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <catch2/catch_test_macros.hpp>

#include "MockConnectionList.hpp"
#include "net/MockNetworkInterface.hpp"
#include "wpi/util/Logger.hpp"

namespace {

class AttemptCountingLogger : public wpi::util::Logger {
 public:
  AttemptCountingLogger() {
    set_min_level(wpi::util::WPI_LOG_DEBUG4);
    SetLogger([this](unsigned int, const char*, unsigned int, const char* msg) {
      if (std::string_view{msg}.find("starting connection attempt (") !=
          std::string_view::npos) {
        ++connectionAttempts;
      }
    });
  }

  std::atomic<size_t> connectionAttempts{0};
};

class TestNetworkClient : public wpi::nt::NetworkClientBase {
 public:
  TestNetworkClient(wpi::nt::net::ILocalStorage& localStorage,
                    wpi::nt::IConnectionList& connList,
                    wpi::util::Logger& logger)
      : NetworkClientBase{0, "test", localStorage, connList, logger} {}

  std::vector<std::pair<std::string, unsigned int>> ResolveSystemCoreServers(
      size_t count) {
    std::vector<std::pair<std::string, unsigned int>> resolvedServers;
    m_loopRunner.ExecSync([&](wpi::net::uv::Loop& loop) {
      m_parallelConnect = wpi::net::ParallelTcpConnector::Create(
          loop, wpi::net::uv::Timer::Time{60'000}, m_logger,
          [](wpi::net::uv::Tcp&) {}, true);

      for (size_t i = 0; i < count; ++i) {
        ProcessSystemCoreData({
            .serviceName = "SystemCore-FIRST-" + std::to_string(i),
            .host = "192.0.2." + std::to_string(i + 1),
            .port = 5810,
        });
      }

      resolvedServers = m_resolvedServers;
      m_parallelConnect->Close();
      m_parallelConnect.reset();
    });
    return resolvedServers;
  }

  void SetServers(
      std::span<const std::pair<std::string, unsigned int>> servers) override {
    DoSetServers(servers, NT_DEFAULT_PORT);
  }

  void SetServers(std::span<const std::pair<std::string, unsigned int>> servers,
                  const ServerResolver& resolver) override {
    DoSetServers(servers, resolver, NT_DEFAULT_PORT);
  }

 private:
  void TcpConnected(wpi::net::uv::Tcp&) override {}
  void ForceDisconnect(std::string_view) override {}
};

}  // namespace

TEST_CASE("Network client caps mDNS-resolved servers", "[network][mdns]") {
  wpi::nt::net::MockLocalStorage localStorage;
  wpi::nt::MockConnectionList connList;
  AttemptCountingLogger logger;
  TestNetworkClient client{localStorage, connList, logger};

  auto resolvedServers = client.ResolveSystemCoreServers(32);

  REQUIRE(resolvedServers.size() == 16);
  CHECK(resolvedServers.front() ==
        std::pair<std::string, unsigned int>{"192.0.2.1", 5810});
  CHECK(resolvedServers.back() ==
        std::pair<std::string, unsigned int>{"192.0.2.16", 5810});

  // Each accepted event updates the connector.  It starts 1 + ... + 16 real
  // TCP attempts, rather than continuing to amplify work for all 32 events.
  CHECK(logger.connectionAttempts == 136);
}
