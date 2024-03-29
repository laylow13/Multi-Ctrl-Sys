import rospy
from mavros_msgs.msg import GlobalPositionTarget, State, PositionTarget
from mavros_msgs.srv import CommandBool, CommandTOL, SetMode
from geometry_msgs.msg import PoseStamped, Twist, Vector3
from sensor_msgs.msg import Imu, NavSatFix
from std_msgs.msg import Float32, Float64, String
import time
from pyquaternion import Quaternion
import math
import threading


class Px4Controller:

    def __init__(self):

        self.imu = None
        self.gps = None
        self.local_pose = None
        self.current_state = None
        self.current_heading = None
        self.takeoff_height = 3.2
        self.local_enu_position = None

        self.cur_target_pose = None
        self.global_target = None

        self.received_new_task = False
        self.arm_state = False
        self.offboard_state = False
        self.received_imu = False
        self.frame = "BODY"

        self.state = None
        self.isvel = False
        self.space_limit = {'x1': 0, 'x2': 0, 'y1': 0, 'y2': 0, 'z': 1}
        self.space_limit_enable = False

        '''
        ros subscribers
        '''
        self.local_pose_sub = rospy.Subscriber(
            "/mavros/local_position/pose", PoseStamped, self.local_pose_callback)
        self.mavros_sub = rospy.Subscriber(
            "/mavros/state", State, self.mavros_state_callback)
        self.gps_sub = rospy.Subscriber(
            "/mavros/global_position/global", NavSatFix, self.gps_callback)
        self.imu_sub = rospy.Subscriber(
            "/mavros/imu/data", Imu, self.imu_callback)

        self.set_target_position_sub = rospy.Subscriber(
            "gi/set_pose/position", PoseStamped, self.set_target_position_callback)
        self.set_target_yaw_sub = rospy.Subscriber(
            "gi/set_pose/orientation", Float32, self.set_target_yaw_callback)
        self.custom_activity_sub = rospy.Subscriber(
            "gi/set_activity/type", String, self.custom_activity_callback)

        '''
        ros publishers
        '''
        self.local_target_pub = rospy.Publisher(
            'mavros/setpoint_raw/local', PositionTarget, queue_size=10)
        self.local_vel_pub = rospy.Publisher(
            'mavros/setpoint_velocity/cmd_vel_unstamped', Twist, queue_size=10)

        '''
        ros services
        '''
        self.armService = rospy.ServiceProxy('/mavros/cmd/arming', CommandBool)
        self.flightModeService = rospy.ServiceProxy(
            '/mavros/set_mode', SetMode)

        '''
        ros parameters
        '''
        rospy.set_param('/mavros/isvel',False)

        print("Px4 Controller Initialized!")


    def start(self):
        rospy.init_node("offboard_node")

        for i in range(10):
            if self.current_heading is not None:
                break
            else:
                print("Waiting for initialization.")
                time.sleep(0.5)

        self.cur_target_pose = self.construct_target(
            0, 0, self.takeoff_height, self.current_heading)
        self.cur_target_vel = self.construct_vel_target(0, 0, 0.3)

        rate = rospy.Rate(20)

        for i in range(100):
            self.local_target_pub.publish(self.cur_target_pose)
            rate.sleep()

        self.space_limit_enable = False

        # if self.takeoff_detection():
        #     print("Vehicle Took Off!")

        # else:
        #     print("Vehicle Took Off Failed!")
        #     return

        '''
        main ROS thread
        '''
        # while self.arm_state and self.offboard_state and (rospy.is_shutdown() is False):

        #     self.local_target_pub.publish(self.cur_target_pose)

        #     if (self.state is "LAND") and (self.local_pose.pose.position.z < 0.15):

        #         if(self.disarm()):

        #             self.state = "DISARMED"

        #     rate.sleep()
        i = 0
        last_request = rospy.Time.now()
        while not rospy.is_shutdown():
            if(self.mavros_state.mode != 'OFFBOARD' and (rospy.Time.now() - last_request > rospy.Duration(5.0))):
                if self.offboard():
                    print ("Offboard enabled")
                    last_request = rospy.Time.now()
            elif (not self.mavros_state.armed and (rospy.Time.now() - last_request > rospy.Duration(5.0))):
                if self.arm():
                    print("Vehicle armed")
                last_request = rospy.Time.now()

            elif (self.state is "LAND") and (self.local_pose.pose.position.z < 0.15):
                if(self.disarm()):
                    self.state = "DISARMED"

            self.isvel=rospy.get_param('/mavros/isvel')

            if self.space_limit_enable:
                self.space_limit_detection()

            if not self.isvel:
                self.local_target_pub.publish(self.cur_target_pose)
            else:
                self.local_vel_pub.publish(self.cur_target_vel)
            # else:

            #     self.local_vel_pub.publish(target_vel)

            # print(self.mavros_state)
            # local_vel_pub.publish(vel)
            #print current_state
            i = i+1
            rate.sleep()

    def construct_target(self, x, y, z, yaw, yaw_rate=1, vx=0, vy=0, vz=0):
        target_raw_pose = PositionTarget()
        target_raw_pose.header.stamp = rospy.Time.now()
        target_raw_pose.coordinate_frame = 1

        # print("Position setpoint mode")
        target_raw_pose.position.x = x
        target_raw_pose.position.y = y
        target_raw_pose.position.z = z

        target_raw_pose.type_mask = PositionTarget.IGNORE_AFX + \
            PositionTarget.IGNORE_AFY + PositionTarget.IGNORE_AFZ\
            + PositionTarget.FORCE+PositionTarget.IGNORE_VX +\
            PositionTarget.IGNORE_VY+PositionTarget.IGNORE_VZ

        # target_raw_pose.type_mask = PositionTarget.IGNORE_VX + PositionTarget.IGNORE_VY + PositionTarget.IGNORE_VZ \
        #     + PositionTarget.IGNORE_AFX + PositionTarget.IGNORE_AFY + PositionTarget.IGNORE_AFZ \
        #     + PositionTarget.FORCE

        target_raw_pose.yaw = yaw
        target_raw_pose.yaw_rate = yaw_rate

        return target_raw_pose

    '''
    cur_p : poseStamped
    target_p: positionTarget
    '''

    def construct_vel_target(self, lx, ly, lz, ax=0, ay=0, az=0):
        target_vel = Twist()
        target_vel.linear.x = lx
        target_vel.linear.y = ly
        target_vel.linear.z = lz
        target_vel.angular.x = ax
        target_vel.angular.y = ay
        target_vel.angular.z = az
        return target_vel

    def set_space_limit(self, x1, x2, y1, y2, z):
        self.space_limit['x1'] = x1
        self.space_limit['x2'] = x2
        self.space_limit['x1'] = x1
        self.space_limit['x2'] = x2
        self.space_limit['z'] = z

    def space_limit_detection(self):
        if (self.local_pose.pose.position.x <= self.space_limit['x2'] and self.local_pose.pose.position.x >= self.space_limit['x1']
            and self.local_pose.pose.position.y <= self.space_limit['y2'] and self.local_pose.pose.position.y >= self.space_limit['y1']
                and self.local_pose.pose.position.z <= self.space_limit['z']):
            pass
        else:
            self.isvel = False
            # like failsafe options

    def position_distance(self, cur_p, target_p, threshold=0.1):
        delta_x = math.fabs(cur_p.pose.position.x - target_p.position.x)
        delta_y = math.fabs(cur_p.pose.position.y - target_p.position.y)
        delta_z = math.fabs(cur_p.pose.position.z - target_p.position.z)

        if (delta_x + delta_y + delta_z < threshold):
            return True
        else:
            return False

    def local_pose_callback(self, msg):
        self.local_pose = msg
        self.local_enu_position = msg

    def mavros_state_callback(self, msg):
        self.mavros_state = msg

    def imu_callback(self, msg):
        global global_imu, current_heading
        self.imu = msg

        self.current_heading = self.q2yaw(self.imu.orientation)

        self.received_imu = True

    def gps_callback(self, msg):
        self.gps = msg

    def FLU2ENU(self, msg):

        FLU_x = msg.pose.position.x * \
            math.cos(self.current_heading) - msg.pose.position.y * \
            math.sin(self.current_heading)
        FLU_y = msg.pose.position.x * \
            math.sin(self.current_heading) + msg.pose.position.y * \
            math.cos(self.current_heading)
        FLU_z = msg.pose.position.z

        return FLU_x, FLU_y, FLU_z

    def set_target_position_callback(self, msg):
        print("Received New Position Task!")

        if msg.header.frame_id == 'base_link':
            '''
            BODY_FLU
            '''
            # For Body frame, we will use FLU (Forward, Left and Up)
            #           +Z     +X
            #            ^    ^
            #            |  /
            #            |/
            #  +Y <------body

            self.frame = "BODY"

            print("body FLU frame")

            ENU_X, ENU_Y, ENU_Z = self.FLU2ENU(msg)

            ENU_X = ENU_X + self.local_pose.pose.position.x
            ENU_Y = ENU_Y + self.local_pose.pose.position.y
            ENU_Z = ENU_Z + self.local_pose.pose.position.z

            self.cur_target_pose = self.construct_target(ENU_X,
                                                         ENU_Y,
                                                         ENU_Z,
                                                         self.current_heading)

        else:
            '''
            LOCAL_ENU
            '''
            # For world frame, we will use ENU (EAST, NORTH and UP)
            #     +Z     +Y
            #      ^    ^
            #      |  /
            #      |/
            #    world------> +X

            self.frame = "LOCAL_ENU"
            print("local ENU frame")

            self.cur_target_pose = self.construct_target(msg.pose.position.x,
                                                         msg.pose.position.y,
                                                         msg.pose.position.z,
                                                         self.current_heading)

    '''
     Receive A Custom Activity
     '''

    def custom_activity_callback(self, msg):

        print("Received Custom Activity:", msg.data)

        if msg.data == "LAND":
            print("LANDING!")
            self.state = "LAND"
            self.cur_target_pose = self.construct_target(self.local_pose.pose.position.x,
                                                         self.local_pose.pose.position.y,
                                                         0.1,
                                                         self.current_heading)

        if msg.data == "HOVER":
            print("HOVERING!")
            self.state = "HOVER"
            self.hover()

        else:
            print("Received Custom Activity:", msg.data, "not supported yet!")

    def set_target_yaw_callback(self, msg):
        print("Received New Yaw Task!")

        yaw_deg = msg.data * math.pi / 180.0
        self.cur_target_pose = self.construct_target(self.local_pose.pose.position.x,
                                                     self.local_pose.pose.position.y,
                                                     self.local_pose.pose.position.z,
                                                     yaw_deg)

    '''
    return yaw from current IMU
    '''

    def q2yaw(self, q):
        if isinstance(q, Quaternion):
            rotate_z_rad = q.yaw_pitch_roll[0]
        else:
            q_ = Quaternion(q.w, q.x, q.y, q.z)
            rotate_z_rad = q_.yaw_pitch_roll[0]

        return rotate_z_rad

    def arm(self):
        if self.armService(True):
            self.arm_state = True
            return True
        else:
            print("Vehicle arming failed!")
            self.arm_state = False
            return False

    def disarm(self):
        if self.armService(False):
            return True
        else:
            print("Vehicle disarming failed!")
            return False

    def offboard(self):
        if self.flightModeService(custom_mode='OFFBOARD'):
            self.offboard_state = True
            return True
        else:
            print("Vechile Offboard failed")
            return False

    def hover(self):

        self.cur_target_pose = self.construct_target(self.local_pose.pose.position.x,
                                                     self.local_pose.pose.position.y,
                                                     self.local_pose.pose.position.z,
                                                     self.current_heading)

    def takeoff_detection(self):
        if self.local_pose.pose.position.z > 0.1 and self.offboard_state and self.arm_state:
            return True
        else:
            return False


if __name__ == '__main__':
    con = Px4Controller()
    con.start()
