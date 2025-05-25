import time
import numpy as np
from collections import deque
from pyproj import CRS, Transformer

# Only import GeoidHeight if needed (pyproj >= 3.6.0)
try:
    from pyproj import GeoidHeight
    HAS_GEOID = True
except ImportError:
    HAS_GEOID = False

class GnssExtrapolator:
    """
    GNSS extrapolator using local ENU projection for high accuracy.
    Reference point is set automatically from the first GNSS fix (using ellipsoid height as ref_height).
    Calculates hMSL using a geoid model (best) or local offset (fast fallback).
    """

    def __init__(self, max_buffer=2, hmsl_mode='geoid', geoid_model="egm96-5"):
        """
        hmsl_mode: 'geoid' (default, best) or 'offset' (fast, local)
        geoid_model: e.g., 'egm96-5', 'egm96-15', 'egm2008-1', etc.
        """
        self.ref_lat = None
        self.ref_lon = None
        self.ref_height = None
        self.ref_ecef = None
        self.buffer = deque(maxlen=max_buffer)
        self.transformers_initialized = False

        # Set up pyproj transformers (do not depend on ref point)
        self.crs_wgs84 = CRS.from_epsg(4979)  # WGS84 3D
        self.crs_ecef = CRS.from_epsg(4978)   # ECEF
        self.transformer_lla_to_ecef = Transformer.from_crs(self.crs_wgs84, self.crs_ecef, always_xy=True)
        self.transformer_ecef_to_lla = Transformer.from_crs(self.crs_ecef, self.crs_wgs84, always_xy=True)

        # hMSL calculation mode
        self.hmsl_mode = hmsl_mode
        self.geoid_offset = None
        self.geoid_model = geoid_model
        if hmsl_mode == 'geoid' and HAS_GEOID:
            self.geoid = GeoidHeight(geoid_model)
        else:
            self.geoid = None

    def lla_to_ecef(self, lat, lon, height):
        x, y, z = self.transformer_lla_to_ecef.transform(lon, lat, height)
        return np.array([x, y, z])

    def ecef_to_lla(self, x, y, z):
        lon, lat, height = self.transformer_ecef_to_lla.transform(x, y, z)
        return lat, lon, height

    def lla_to_enu(self, lat, lon, height):
        if self.ref_ecef is None:
            raise ValueError("Reference ECEF not set.")
        xyz = self.lla_to_ecef(lat, lon, height)
        dx = xyz - self.ref_ecef
        phi = np.radians(self.ref_lat)
        lam = np.radians(self.ref_lon)
        t = np.array([
            [-np.sin(lam),              np.cos(lam),             0],
            [-np.sin(phi)*np.cos(lam), -np.sin(phi)*np.sin(lam), np.cos(phi)],
            [np.cos(phi)*np.cos(lam),  np.cos(phi)*np.sin(lam),  np.sin(phi)]
        ])
        enu = t @ dx
        return enu  # [e, n, u]

    def enu_to_lla(self, e, n, u):
        if self.ref_ecef is None:
            raise ValueError("Reference ECEF not set.")
        phi = np.radians(self.ref_lat)
        lam = np.radians(self.ref_lon)
        t = np.array([
            [-np.sin(lam), -np.sin(phi)*np.cos(lam),  np.cos(phi)*np.cos(lam)],
            [ np.cos(lam), -np.sin(phi)*np.sin(lam),  np.cos(phi)*np.sin(lam)],
            [          0,              np.cos(phi),              np.sin(phi)]
        ])
        dx = t @ np.array([e, n, u])
        xyz = self.ref_ecef + dx
        lat, lon, height = self.ecef_to_lla(*xyz)
        return lat, lon, height

    def ellipsoid_to_hmsl(self, lat, lon, height):
        """Convert ellipsoid height to mean sea level (hMSL)."""
        if self.hmsl_mode == 'geoid' and self.geoid is not None:
            undulation = self.geoid.height(lon, lat)
            hmsl = height - undulation
            return hmsl
        elif self.hmsl_mode == 'offset' and self.geoid_offset is not None:
            return height - self.geoid_offset
        else:
            return None  # Can't compute hMSL

    def add_fix(self, gnss_fix):
        """
        Add a new GNSS fix.
        gnss_fix: dict with at least 'timestamp', 'lat', 'lon', 'height', 'velE', 'velN', 'velD' (all in SI units)
        Optionally, 'hMSL' for offset mode.
        """
        if self.ref_lat is None:
            self.ref_lat = gnss_fix['lat']
            self.ref_lon = gnss_fix['lon']
            self.ref_height = gnss_fix.get('height', 0)
            self.ref_ecef = self.lla_to_ecef(self.ref_lat, self.ref_lon, self.ref_height)
            self.transformers_initialized = True
        # Update geoid offset if both values are present and using offset mode
        if self.hmsl_mode == 'offset' and 'height' in gnss_fix and 'hMSL' in gnss_fix:
            self.geoid_offset = gnss_fix['height'] - gnss_fix['hMSL']
        self.buffer.append(gnss_fix)

    def extrapolate(self, target_time=None):
        """
        Extrapolate GNSS position to the given target_time (epoch seconds).
        Returns a dict with extrapolated 'lat', 'lon', 'height', 'hMSL', and 'timestamp'.
        """
        if not self.transformers_initialized or len(self.buffer) < 2:
            return None

        last = self.buffer[-1]
        prev = self.buffer[-2]
        if target_time is None:
            target_time = time.time()

        dt = target_time - last['timestamp']
        if dt < 0:
            return last.copy()

        # Use ellipsoid height for all geodetic math
        h_last = last.get('height', 0)
        h_prev = prev.get('height', 0)
        # Convert both fixes to ENU coordinates
        e1, n1, u1 = self.lla_to_enu(last['lat'], last['lon'], h_last)
        e0, n0, u0 = self.lla_to_enu(prev['lat'], prev['lon'], h_prev)

        # Use velocity if available, else estimate from last two fixes
        if all(k in last for k in ('velE', 'velN', 'velD')):
            de = last['velE'] * dt
            dn = last['velN'] * dt
            du = last['velD'] * dt
        else:
            dt_pos = last['timestamp'] - prev['timestamp']
            if dt_pos == 0:
                de = dn = du = 0
            else:
                de = (e1 - e0) / dt_pos * dt
                dn = (n1 - n0) / dt_pos * dt
                du = (u1 - u0) / dt_pos * dt

        e_ex = e1 + de
        n_ex = n1 + dn
        u_ex = u1 + du

        # Convert back to lat, lon, height (ellipsoid)
        lat, lon, height = self.enu_to_lla(e_ex, n_ex, u_ex)
        hmsl = self.ellipsoid_to_hmsl(lat, lon, height)

        extrapolated = {
            'timestamp': target_time,
            'lat': lat,
            'lon': lon,
            'height': height,
            'hMSL': hmsl,
        }
        return extrapolated