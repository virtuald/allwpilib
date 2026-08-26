import random

import pytest

from wpimath import (
    DrivetrainSplineTrajectoryGenerator,
    Pose2d,
    Pose3d,
    Rotation2d,
    Rotation3d,
    TrajectoryConfig,
    TwoDeadWheelOdometry3d,
)


@pytest.fixture
def odometry():
    return TwoDeadWheelOdometry3d(1, 1, 0, 0, Rotation3d(), Pose3d())


def _assert_pose(pose, x, y, z, roll, pitch, yaw, tolerance=0.01):
    assert pose.x == pytest.approx(x, abs=tolerance)
    assert pose.y == pytest.approx(y, abs=tolerance)
    assert pose.z == pytest.approx(z, abs=tolerance)
    assert pose.rotation().x == pytest.approx(roll, abs=tolerance)
    assert pose.rotation().y == pytest.approx(pitch, abs=tolerance)
    assert pose.rotation().z == pytest.approx(yaw, abs=tolerance)


def test_multiple_consecutive_updates(odometry):
    odometry.reset_position(1, 1, Rotation3d(), Pose3d())

    odometry.update(1, 1, Rotation3d())
    pose = odometry.update(1, 1, Rotation3d())

    _assert_pose(pose, 0, 0, 0, 0, 0, 0)


def test_two_iterations(odometry):
    odometry.reset_position(0, 0, Rotation3d(), Pose3d())

    odometry.update(0, 0, Rotation3d())
    pose = odometry.update(0.1, 0, Rotation3d())

    _assert_pose(pose, 0.1, 0, 0, 0, 0, 0)


def test_gyro_angle_reset(odometry):
    gyro_angle = Rotation3d(0, 0, Rotation2d.from_degrees(90).radians())
    odometry.reset_position(0, 0, gyro_angle, Pose3d())

    odometry.update(1, 0, gyro_angle)
    pose = odometry.update(1, 0, gyro_angle)

    _assert_pose(pose, 1, 0, 0, 0, 0, 0)


@pytest.mark.parametrize(
    ("x_wheel_velocity", "y_wheel_velocity", "omega", "expected"),
    [
        (5, 0, 0, (5, 0, 0)),
        (0, 5, 0, (0, 5, 0)),
        (-5, 5, 5, (0, 0, 5)),
        (1, -1, 5, (6, -6, 5)),
    ],
)
def test_forward_kinematics(
    odometry, x_wheel_velocity, y_wheel_velocity, omega, expected
):
    velocities = odometry.to_chassis_velocities(
        x_wheel_velocity, y_wheel_velocity, omega
    )

    assert velocities.vx == pytest.approx(expected[0], abs=0.1)
    assert velocities.vy == pytest.approx(expected[1], abs=0.1)
    assert velocities.omega == pytest.approx(expected[2], abs=0.1)


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


def _test_accuracy(odometry, face_trajectory):
    trajectory = _trajectory()
    x_wheel_position = 0
    y_wheel_position = 0

    if face_trajectory:
        initial_pose = Pose3d(trajectory.initial_pose())
        gyro_angle = Rotation3d(trajectory.initial_pose().rotation())
    else:
        initial_pose = Pose3d()
        gyro_angle = Rotation3d()
    odometry.reset_position(
        x_wheel_position, y_wheel_position, gyro_angle, initial_pose
    )

    generator = random.Random(5190)
    dt = 0.02
    time = 0.0
    errors = []
    odometry_distance = 0
    trajectory_distance = 0

    while time < trajectory.duration():
        state = trajectory.sample_at(time)
        velocity = state.forward_velocity()
        trajectory_distance += (
            velocity * dt + 0.5 * state.forward_acceleration() * dt * dt
        )
        if face_trajectory:
            vx = velocity
            vy = 0
            omega = velocity * state.curvature
            gyro_angle = Rotation3d(
                state.pose.rotation() + Rotation2d(generator.gauss(0, 0.001))
            )
        else:
            vx = velocity * state.pose.rotation().cos()
            vy = velocity * state.pose.rotation().sin()
            omega = 0
            gyro_angle = Rotation3d(0, 0, generator.gauss(0, 0.001))

        x_wheel_velocity = vx - omega + generator.gauss(0, 0.05)
        y_wheel_velocity = vy + omega + generator.gauss(0, 0.05)
        x_wheel_position += x_wheel_velocity * dt
        y_wheel_position += y_wheel_velocity * dt

        previous_pose = odometry.get_pose()
        estimate = odometry.update(
            x_wheel_position, y_wheel_position, gyro_angle
        )
        odometry_distance += previous_pose.translation().distance(
            estimate.translation()
        )
        errors.append(
            state.pose.translation().distance(
                estimate.translation().to_translation2d()
            )
        )
        time += dt

    assert sum(errors) / len(errors) < 0.1
    assert max(errors) < 0.2
    assert odometry_distance == pytest.approx(trajectory_distance, rel=0.05)


def test_accuracy_facing_trajectory(odometry):
    _test_accuracy(odometry, face_trajectory=True)


def test_accuracy_facing_x_axis(odometry):
    _test_accuracy(odometry, face_trajectory=False)
