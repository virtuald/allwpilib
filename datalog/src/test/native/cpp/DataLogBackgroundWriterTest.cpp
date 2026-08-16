// Copyright (c) FIRST and other WPILib contributors.
// Open Source Software; you can modify and/or share it under the terms of
// the WPILib BSD license file in the root directory of this project.

#include "wpi/datalog/DataLogBackgroundWriter.hpp"

#include <chrono>
#include <filesystem>
#include <fstream>
#include <future>
#include <memory>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <catch2/catch_test_macros.hpp>

namespace {

struct DrainCallbackState {
  DrainCallbackState()
      : releaseFirstDrainFuture{releaseFirstDrain.get_future().share()} {}

  std::promise<void> startupDrainCompleted;
  std::promise<void> firstDrainStarted;
  std::promise<void> releaseFirstDrain;
  std::shared_future<void> releaseFirstDrainFuture;
  std::promise<void> secondDrainStarted;
  int drainCount = 0;
};

struct AutomaticOutputState {
  AutomaticOutputState()
      : outputStarted{outputStartedPromise.get_future().share()} {}

  std::promise<void> outputStartedPromise;
  std::shared_future<void> outputStarted;
  bool outputReported = false;
};

struct TemporaryDirectory {
  TemporaryDirectory() {
    auto suffix = std::chrono::steady_clock::now().time_since_epoch().count();
    path = std::filesystem::temp_directory_path() /
           ("wpilib-datalog-path-test-" + std::to_string(suffix));
    std::filesystem::create_directories(path / "logs");
  }

  ~TemporaryDirectory() { std::filesystem::remove_all(path); }

  std::filesystem::path path;
};

}  // namespace

TEST_CASE("DataLogBackgroundWriterTest ConcurrentDrainDoesNotDeadlock",
          "[datalog][background-writer]") {
  auto writer = std::make_unique<wpi::log::DataLogBackgroundWriter>(
      [](std::span<const uint8_t>) {}, 0.0);
  auto* writerPtr = writer.get();
  int entry = writerPtr->Start("raw", "raw", {}, 1);
  auto payload = std::make_shared<std::vector<uint8_t>>(2 * 1024 * 1024);
  std::promise<void> complete;
  auto completed = complete.get_future();
  std::thread producer{
      [writerPtr, payload, entry, complete = std::move(complete)]() mutable {
        for (int i = 0; i < 8; ++i) {
          writerPtr->AppendRaw(entry, *payload, i + 2);
          writerPtr->Flush();
        }
        complete.set_value();
      }};

  if (completed.wait_for(std::chrono::seconds{2}) !=
      std::future_status::ready) {
    producer.detach();
    writer.release();
    FAIL("background producer and writer deadlocked");
  }
  producer.join();
  writer.reset();
}

TEST_CASE("DataLogBackgroundWriterTest NegativePeriodFlushesAutomatically",
          "[datalog][background-writer]") {
  auto callbackState = std::make_shared<AutomaticOutputState>();
  auto writer = std::make_unique<wpi::log::DataLogBackgroundWriter>(
      [callbackState](std::span<const uint8_t> data) {
        if (!data.empty() && !callbackState->outputReported) {
          callbackState->outputReported = true;
          callbackState->outputStartedPromise.set_value();
        }
      },
      -1.0);

  int entry = writer->Start("raw", "raw", {}, 1);
  writer->AppendRaw(entry, std::vector<uint8_t>{1}, 2);

  bool outputWasPrompt =
      callbackState->outputStarted.wait_for(std::chrono::seconds{1}) ==
      std::future_status::ready;
  writer.reset();
  REQUIRE(outputWasPrompt);
}

TEST_CASE("DataLogBackgroundWriterTest FlushWakesAfterBlockedDrain",
          "[datalog][background-writer]") {
  auto callbackState = std::make_shared<DrainCallbackState>();
  auto startupDrainCompleted =
      callbackState->startupDrainCompleted.get_future();
  auto firstDrainStarted = callbackState->firstDrainStarted.get_future();
  auto secondDrainStarted = callbackState->secondDrainStarted.get_future();
  auto writer = std::make_unique<wpi::log::DataLogBackgroundWriter>(
      [callbackState](std::span<const uint8_t> data) {
        if (data.empty()) {
          return;
        }
        if (++callbackState->drainCount == 1) {
          callbackState->startupDrainCompleted.set_value();
        } else if (callbackState->drainCount == 2) {
          callbackState->firstDrainStarted.set_value();
          callbackState->releaseFirstDrainFuture.wait();
        } else if (callbackState->drainCount == 3) {
          callbackState->secondDrainStarted.set_value();
        }
      },
      30.0);

  auto startupDeadline =
      std::chrono::steady_clock::now() + std::chrono::seconds{2};
  do {
    writer->Flush();
    if (startupDrainCompleted.wait_for(std::chrono::milliseconds{10}) ==
        std::future_status::ready) {
      break;
    }
  } while (std::chrono::steady_clock::now() < startupDeadline);

  if (startupDrainCompleted.wait_for(std::chrono::seconds{0}) !=
      std::future_status::ready) {
    callbackState->releaseFirstDrain.set_value();
    writer.reset();
    FAIL("background writer startup drain did not complete");
  }

  int entry = writer->Start("raw", "raw", {}, 1);
  std::vector<uint8_t> payload{1};
  writer->AppendRaw(entry, payload, 2);
  auto firstDrainDeadline =
      std::chrono::steady_clock::now() + std::chrono::seconds{2};
  do {
    writer->Flush();
    if (firstDrainStarted.wait_for(std::chrono::milliseconds{10}) ==
        std::future_status::ready) {
      break;
    }
  } while (std::chrono::steady_clock::now() < firstDrainDeadline);

  if (firstDrainStarted.wait_for(std::chrono::seconds{0}) !=
      std::future_status::ready) {
    callbackState->releaseFirstDrain.set_value();
    writer.reset();
    FAIL("first data drain did not start");
  }

  writer->AppendRaw(entry, payload, 3);
  writer->Flush();
  callbackState->releaseFirstDrain.set_value();

  bool secondDrainWasPrompt =
      secondDrainStarted.wait_for(std::chrono::seconds{1}) ==
      std::future_status::ready;
  writer.reset();
  REQUIRE(secondDrainWasPrompt);
}

TEST_CASE("DataLogBackgroundWriterTest FilenameCannotEscapeDirectory",
          "[datalog][background-writer]") {
  TemporaryDirectory temp;
  auto logDir = temp.path / "logs";
  auto victim = temp.path / "victim.txt";
  {
    std::ofstream out{victim};
    out << "ORIGINAL";
  }

  {
    wpi::log::DataLogBackgroundWriter log{logDir.string(), "safe.wpilog", 0.01};
    for (int i = 0; i < 200 && !std::filesystem::exists(logDir / "safe.wpilog");
         ++i) {
      std::this_thread::sleep_for(std::chrono::milliseconds{5});
    }
    REQUIRE(std::filesystem::exists(logDir / "safe.wpilog"));
    log.SetFilename("../victim.txt");
    log.Flush();
    std::this_thread::sleep_for(std::chrono::milliseconds{100});
  }

  std::ifstream in{victim};
  std::string contents;
  in >> contents;
  CHECK(contents == "ORIGINAL");

  auto escaped = temp.path / "escaped.wpilog";
  {
    wpi::log::DataLogBackgroundWriter log{logDir.string(), "../escaped.wpilog",
                                          0.01};
    std::this_thread::sleep_for(std::chrono::milliseconds{100});
  }
  CHECK_FALSE(std::filesystem::exists(escaped));
}
