import numpy as np
import pygame

import bluesky as bs
from bluesky.simulation import ScreenIO

import gymnasium as gym
from gymnasium import spaces

class ScreenDummy(ScreenIO):
    """
    Dummy class for the screen. Inherits from ScreenIO to make sure all the
    necessary methods are there. This class is there to reimplement the echo
    method so that console messages are ignored.
    """
    def echo(self, text='', flags=0):
        pass

class DescendEnv(gym.Env):
    """ 
    Very simple environment that requires the agent to climb / descend to a target altitude.
    As the runway approaches the aircraft has to start descending, knowing when to start
    the descend.

    TODO:
    - rendering
    - better commenting
    - proper normalization functionality
    - Monitor Wrapper class for monitoring progress, can be something to be used by all envs.
    """

    # information regarding the possible rendering modes of the environment
    # for BlueSkyGym probably only implement 1 for now together with None, which is default
    metadata = {"render_modes": ["rgb_array","human"], "render_fps": 120}

    def __init__(self, render_mode=None):
        self.window_width = 512
        self.window_height = 256
        self.window_size = (self.window_width, self.window_height) # Size of the rendered environment

        self.observation_space = spaces.Dict(
            {
                "altitude": spaces.Box(-np.inf, np.inf, dtype=np.float64),
                "vz": spaces.Box(-np.inf, np.inf, dtype=np.float64),
                "target_altitude": spaces.Box(-np.inf, np.inf, dtype=np.float64),
                "runway_distance": spaces.Box(-np.inf, np.inf, dtype=np.float64)
            }
        )
       
        self.action_space = spaces.Box(-1, 1, shape=(1,), dtype=np.float64)

        assert render_mode is None or render_mode in self.metadata["render_modes"]
        self.render_mode = render_mode

        # initialize bluesky as non-networked simulation node
        bs.init(mode='sim', detached=True)

        # initialize dummy screen and set correct sim speed
        bs.scr = ScreenDummy()
        bs.stack.stack('DT 1;FF')

        """
        If human-rendering is used, `self.window` will be a reference
        to the window that we draw to. `self.clock` will be a clock that is used
        to ensure that the environment is rendered at the correct framerate in
        human-mode. They will remain `None` until human-mode is used for the
        first time.
        """
        self.window = None
        self.clock = None


    def _get_obs(self):
        """
        Observation consists of altitude, vertical speed, target altitude and distance to runway
        Very crude normalization in place for now
        """

        self.altitude = bs.traf.alt[0]
        self.vz = bs.traf.vs[0]
        self.runway_distance = (200 - bs.tools.geo.kwikdist(52,4,bs.traf.lat[0],bs.traf.lon[0])*1.852)

        # very crude normalization
        obs_altitude = np.array([(self.altitude - 1500)/3000])
        obs_vz = np.array([self.vz / 5])
        obs_target_alt = np.array([((self.target_alt- 1500)/3000)])
        obs_runway_distance = np.array([(self.runway_distance-100)/200])

        observation = {
                "altitude": obs_altitude,
                "vz": obs_vz,
                "target_altitude": obs_target_alt,
                "runway_distance": obs_runway_distance,
            }
        
        return observation
    
    def _get_info(self):
        # Here you implement any additional info that you want to return after a step,
        # but that should not be used by the agent for decision making, so used for logging and debugging purposes
        # for now just have 10, because it crashed if I gave none for some reason.
        return {
            "distance": 10
        }
    def _get_reward(self):

        # reward part of the function
        if self.runway_distance > 0 and self.altitude > 0:
            return abs(self.target_alt - self.altitude)*-5/3000, 0
        elif self.altitude <= 0:
            return -100, 1
        elif self.runway_distance <= 0:
            return abs(100-self.altitude)*-50/3000, 1
        
    def _get_action(self,action):
        # Transform action to the meters per second
        action = action * 12.5

        # Bluesky interpretes vertical velocity command through altitude commands 
        # with a vertical speed (magnitude). So check sign of action and give arbitrary 
        # altitude command

        # The actions are then executed through stack commands;
        if action >= 0:
            bs.traf.selalt[0] = 1000000
            bs.traf.selvs[0] = action
        elif action < 0:
            bs.traf.selalt[0] = 0
            bs.traf.selvs[0] = action

    def reset(self, seed=None, options=None):
        
        super().reset(seed=seed)

        alt_init = np.random.randint(2000, 4000)
        self.target_alt = alt_init + np.random.randint(-500,500)

        bs.traf.cre('KL001',actype="A320",acalt=alt_init,acspd=150)
        bs.traf.swvnav[0] = False

        observation = self._get_obs()
        info = self._get_info()

        if self.render_mode == "human":
            self._render_frame()

        return observation, info
    
    def step(self, action):
        
        self._get_action(action)

        action_frequency = 30
        for i in range(action_frequency):
            bs.sim.step()
            if self.render_mode == "human":
                self._render_frame()
                observation = self._get_obs()

        observation = self._get_obs()
        reward, terminated = self._get_reward()

        info = self._get_info()

        if terminated:
            for acid in bs.traf.id:
                idx = bs.traf.id2idx(acid)
                bs.traf.delete(idx)

        return observation, reward, terminated, False, info
    
    def render(self):
        pass

    def _render_frame(self):
        if self.window is None and self.render_mode == "human":
            pygame.init()
            pygame.display.init()
            self.window = pygame.display.set_mode(self.window_size)

        if self.clock is None and self.render_mode == "human":
            self.clock = pygame.time.Clock()

        zero_offset = 25
        max_distance = 180 # width of screen in km

        canvas = pygame.Surface(self.window_size)
        canvas.fill((135,206,235))

        # draw a ground surface
        pygame.draw.rect(
            canvas, 
            (154,205,50),
            pygame.Rect(
                (0,self.window_height-50),
                (self.window_width, 50)
                ),
        )
        
        # draw target altitude
        max_alt = 5000
        target_alt = int((-1*(self.target_alt-max_alt)/max_alt)*(self.window_height-50))

        pygame.draw.line(
            canvas,
            (255,255,255),
            (0,target_alt),
            (self.window_width,target_alt)
        )

        # draw runway
        runway_length = 30
        runway_start = int(((self.runway_distance + zero_offset)/max_distance)*self.window_width)
        runway_end = int(runway_start + (runway_length/max_distance)*self.window_width)

        pygame.draw.line(
            canvas,
            (119,136,153),
            (runway_start,self.window_height - 50),
            (runway_end,self.window_height - 50),
            width = 3
        )

        # draw aircraft
        aircraft_alt = int((-1*(self.altitude-max_alt)/max_alt)*(self.window_height-50))
        aircraft_start = int(((zero_offset)/max_distance)*self.window_width)
        aircraft_end = int(aircraft_start + (4/max_distance)*self.window_width)

        pygame.draw.line(
            canvas,
            (0,0,0),
            (aircraft_start,aircraft_alt),
            (aircraft_end,aircraft_alt),
            width = 5
        )

        self.window.blit(canvas, canvas.get_rect())
        pygame.display.update()
        self.clock.tick(self.metadata["render_fps"])
        
    def close(self):
        pass