import math
import random
from collections import deque
from functools import cache

import pytest

from wpimath import (
    ChassisVelocities,
    DrivetrainSplineTrajectoryGenerator,
    Pose2d,
    Rotation2d,
    TrajectoryConfig,
    Transform2d,
    Translation2d,
    TwoDeadWheelPoseEstimator,
)


def _make_estimator(state_std_devs=(0.1, 0.1, 0.1), vision_std_devs=(0.45, 0.45, 0.45)):
    return TwoDeadWheelPoseEstimator(
        1,
        1,
        0,
        0,
        Rotation2d(),
        Pose2d(),
        state_std_devs,
        vision_std_devs,
    )


@cache
def _trajectory():
    return DrivetrainSplineTrajectoryGenerator.generate(
        [
            Pose2d(0, 0, Rotation2d.from_degrees(45)),
            Pose2d(3, 0, Rotation2d.from_degrees(-90)),
            Pose2d(0, 0, Rotation2d.from_degrees(135)),
            Pose2d(-3, 0, Rotation2d.from_degrees(-90)),
            Pose2d(0, 0, Rotation2d.from_degrees(45)),
        ],
        TrajectoryConfig(2, 2),
    )


def _follow_trajectory(estimator, trajectory, starting_pose, check_error):
    x_wheel_position = 0
    y_wheel_position = 0
    estimator.reset_position(0, 0, Rotation2d(), starting_pose)

    generator = random.Random(5190)
    pending_vision = deque()
    dt = 0.02
    time = 0.0
    errors = []

    while time < trajectory.duration():
        state = trajectory.sample_at(time)

        if not pending_vision or pending_vision[-1][0] + 0.1 < time:
            vision_pose = state.pose + Transform2d(
                Translation2d(generator.gauss(0, 0.1), generator.gauss(0, 0.1)),
                Rotation2d(generator.gauss(0, 0.05)),
            )
            pending_vision.append((time, vision_pose))

        if pending_vision and pending_vision[0][0] + 0.25 < time:
            timestamp, vision_pose = pending_vision.popleft()
            estimator.add_vision_measurement(vision_pose, timestamp)

        chassis_velocities = ChassisVelocities(
            state.forward_velocity(),
            0,
            state.forward_velocity() * state.curvature,
        )
        x_wheel_velocity = (
            chassis_velocities.vx
            - chassis_velocities.omega
            + generator.gauss(0, 0.05)
        )
        y_wheel_velocity = (
            chassis_velocities.vy
            + chassis_velocities.omega
            + generator.gauss(0, 0.05)
        )
        x_wheel_position += x_wheel_velocity * dt
        y_wheel_position += y_wheel_velocity * dt

        estimate = estimator.update_with_time(
            time,
            x_wheel_position,
            y_wheel_position,
            state.pose.rotation()
            + Rotation2d(generator.gauss(0, 0.001))
            - trajectory.initial_pose().rotation(),
        )
        errors.append(state.pose.translation().distance(estimate.translation()))
        time += dt

    estimate = estimator.get_estimated_position()
    assert estimate.x == pytest.approx(0, abs=0.08)
    assert estimate.y == pytest.approx(0, abs=0.08)
    assert estimate.rotation().degrees() == pytest.approx(45, abs=math.degrees(0.15))

    if check_error:
        assert sum(errors) / len(errors) < 0.058
        assert max(errors) < 0.2


def test_accuracy_facing_trajectory():
    trajectory = _trajectory()
    _follow_trajectory(
        _make_estimator(), trajectory, trajectory.initial_pose(), check_error=True
    )


@pytest.mark.parametrize("offset_direction_degrees", range(0, 360, 45))
@pytest.mark.parametrize("offset_heading_degrees", range(0, 360, 45))
def test_corrects_bad_initial_pose(
    offset_direction_degrees, offset_heading_degrees
):
    trajectory = _trajectory()
    direction = Rotation2d.from_degrees(offset_direction_degrees)
    initial_pose = trajectory.initial_pose() + Transform2d(
        Translation2d(direction.cos(), direction.sin()),
        Rotation2d.from_degrees(offset_heading_degrees),
    )

    _follow_trajectory(
        _make_estimator(vision_std_devs=(0.9, 0.9, 0.9)),
        trajectory,
        initial_pose,
        check_error=False,
    )


def test_simultaneous_vision_measurements_all_affect_estimate():
    initial_pose = Pose2d(1, 2, Rotation2d.from_degrees(270))
    estimator = TwoDeadWheelPoseEstimator(
        1,
        1,
        0,
        0,
        Rotation2d(),
        initial_pose,
        (0.1, 0.1, 0.1),
        (0.45, 0.45, 0.45),
    )
    estimator.update_with_time(0, 0, 0, Rotation2d())
    measurements = [
        Pose2d(0, 0, Rotation2d()),
        Pose2d(3, 1, Rotation2d.from_degrees(90)),
        Pose2d(2, 4, Rotation2d.from_degrees(180)),
    ]

    for _ in range(1000):
        for measurement in measurements:
            estimator.add_vision_measurement(measurement, 0)

    estimate = estimator.get_estimated_position()
    initial_differences = (
        abs(estimate.x - initial_pose.x),
        abs(estimate.y - initial_pose.y),
        abs((estimate.rotation() - initial_pose.rotation()).radians()),
    )
    assert any(difference > 0.08 for difference in initial_differences)

    for measurement in measurements:
        differences = (
            abs(estimate.x - measurement.x),
            abs(estimate.y - measurement.y),
            abs((estimate.rotation() - measurement.rotation()).radians()),
        )
        assert any(difference > 0.08 for difference in differences)


def test_discards_stale_vision_measurements():
    estimator = _make_estimator()
    timestamp = 0.0
    while timestamp < 4:
        estimator.update_with_time(timestamp, 0, 0, Rotation2d())
        timestamp += 0.02

    estimate_before = estimator.get_estimated_position()
    estimator.add_vision_measurement(
        Pose2d(10, 10, Rotation2d(0.1)), 1, (0.1, 0.1, 0.1)
    )
    estimate_after = estimator.get_estimated_position()

    assert estimate_after.x == pytest.approx(estimate_before.x, abs=1e-6)
    assert estimate_after.y == pytest.approx(estimate_before.y, abs=1e-6)
    assert estimate_after.rotation().radians() == pytest.approx(
        estimate_before.rotation().radians(), abs=1e-6
    )


def _assert_sample(estimator, timestamp, x, y, rotation=0):
    sample = estimator.sample_at(timestamp)
    assert sample is not None
    assert sample.x == pytest.approx(x, abs=1e-9, rel=0)
    assert sample.y == pytest.approx(y, abs=1e-9, rel=0)
    assert sample.rotation().radians() == pytest.approx(rotation, abs=1e-9, rel=0)


def test_sample_at_interpolates_and_applies_vision_corrections():
    estimator = _make_estimator(
        state_std_devs=(1, 1, 1), vision_std_devs=(1, 1, 1)
    )
    assert estimator.sample_at(1) is None

    for step in range(51):
        timestamp = 1 + step * 0.02
        estimator.update_with_time(timestamp, timestamp, 0, Rotation2d())

    _assert_sample(estimator, 1.02, 1.02, 0)
    _assert_sample(estimator, 1.01, 1.01, 0)
    _assert_sample(estimator, 0.5, 1, 0)
    _assert_sample(estimator, 2.5, 2, 0)

    estimator.add_vision_measurement(Pose2d(2, 0, Rotation2d(1)), 2.2)
    _assert_sample(estimator, 1.02, 1.02, 0)
    _assert_sample(estimator, 1.01, 1.01, 0)
    _assert_sample(estimator, 0.5, 1, 0)

    estimator.add_vision_measurement(Pose2d(1, 0.2, Rotation2d()), 0.9)
    _assert_sample(estimator, 1.02, 1.02, 0.1)
    _assert_sample(estimator, 1.01, 1.01, 0.1)
    _assert_sample(estimator, 0.5, 1, 0.1)
    _assert_sample(estimator, 2.5, 2, 0.1)


def _assert_pose(estimator, x, y, rotation):
    pose = estimator.get_estimated_position()
    assert pose.x == pytest.approx(x, abs=1e-9, rel=0)
    assert pose.y == pytest.approx(y, abs=1e-9, rel=0)
    assert pose.rotation().radians() == pytest.approx(rotation, abs=1e-9, rel=0)


def test_reset_methods():
    estimator = TwoDeadWheelPoseEstimator(
        1,
        1,
        0,
        0,
        Rotation2d(),
        Pose2d(-1, -1, Rotation2d(1)),
        (1, 1, 1),
        (1, 1, 1),
    )
    _assert_pose(estimator, -1, -1, 1)

    estimator.reset_position(1, 0, Rotation2d(), Pose2d(1, 0, Rotation2d()))
    _assert_pose(estimator, 1, 0, 0)

    pose = estimator.update(2, 0, Rotation2d())
    assert pose.x == pytest.approx(2, abs=1e-9, rel=0)
    _assert_pose(estimator, 2, 0, 0)

    estimator.reset_position(1, 0, Rotation2d(), Pose2d(1, 0, Rotation2d()))
    estimator.update_with_time(0, 2, 0, Rotation2d())
    estimator.add_vision_measurement(Pose2d(3, 0, Rotation2d()), 0)
    _assert_pose(estimator, 2.5, 0, 0)

    estimator.reset_rotation(Rotation2d.from_degrees(90))
    _assert_pose(estimator, 2.5, 0, math.pi / 2)

    estimator.update_with_time(0.02, 3, 0, Rotation2d())
    _assert_pose(estimator, 2.5, 1, math.pi / 2)

    estimator.add_vision_measurement(
        Pose2d(2.5, 1, Rotation2d.from_degrees(180)), 0.02
    )
    _assert_pose(estimator, 2.5, 1, 3 * math.pi / 4)

    estimator.reset_translation(Translation2d(-1, -1))
    _assert_pose(estimator, -1, -1, 3 * math.pi / 4)

    estimator.reset_pose(Pose2d())
    _assert_pose(estimator, 0, 0, 0)
