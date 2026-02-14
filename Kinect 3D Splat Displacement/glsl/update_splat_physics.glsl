// Splat Physics Update Shader (runs as GLSL TOP)
// Simulates per-splat spring-damper physics with Kinect flow as force input.
// All offsets and velocities are stored in world space.
//
// Setup:
//   - Resolution: 1024x1024 (one pixel per splat)
//   - Format: RGBA 32-bit float
//   - Input 0 (sTD2DInputs[0]): Previous offset texture (feedback)
//   - Input 1 (sTD2DInputs[1]): Previous velocity texture (feedback)
//   - Input 2 (sTD2DInputs[2]): Kinect displacement texture (flow.xy, depth.z)
//   - Input 3 (sTD2DInputs[3]): Splat rest positions texture (worldPos.xyz, valid flag in A)
//
// Outputs (MRT):
//   - Location 0: Updated offset (world-space XYZ)
//   - Location 1: Updated velocity (world-space XYZ)

// Physics uniforms
uniform mat4 uDisplaceVP;		// view-projection for projecting splat pos to Kinect UV
uniform vec3 uSplatTranslate;	// splat geometry translation (from TD scene)
uniform vec3 uSplatRotate;		// splat geometry rotation in degrees (from TD scene)
uniform float uSplatScale;		// splat geometry uniform scale (from TD scene)
uniform vec3 uCamRight;			// camera right vector (world space)
uniform vec3 uCamUp;			// camera up vector (world space)
uniform float uForceStrength;	// how much Kinect flow accelerates splats (try 5.0 - 20.0)
uniform float uReturnSpeed;	// how fast offset decays toward zero, 0-1 (try 0.9 - 0.99, higher = slower return)
uniform float uDamping;		// velocity decay per frame, 0-1 (try 0.8 - 0.95)
uniform float uDeltaTime;		// time step in seconds (0.016 for 60fps)
uniform float uDepthFalloff;	// depth weighting curve (try 2.0 - 5.0)
uniform float uMaxOffset;		// safety clamp to prevent splats flying to infinity (try 5.0 - 20.0)
uniform float uNoiseAmount;	// per-splat force scatter, 0-1 (try 0.2 - 0.5)
uniform float uNoiseSpeed;		// how fast noise evolves over time (try 0.5 - 2.0)
uniform float uTime;			// elapsed time in seconds (bind to absTime.seconds)
uniform vec3 uSceneCenter;		// bounding sphere center (world space, from bounds.json)
uniform float uMaxDisplaceRadius;	// max distance from scene center for displacement (0 = unlimited)

// MRT output: set "Number of Color Buffers" to 2 on the GLSL TOP
// Buffer 0 = offset, Buffer 1 = velocity
layout(location = 0) out vec4 fragColor[TD_NUM_COLOR_BUFFERS];

// Hash-based noise (per-splat, time-varying)
vec3 hash3(vec3 p) {
	p = vec3(dot(p, vec3(127.1, 311.7, 74.7)),
	         dot(p, vec3(269.5, 183.3, 246.1)),
	         dot(p, vec3(113.5, 271.9, 124.6)));
	return fract(sin(p) * 43758.5453) * 2.0 - 1.0;
}

// Rotation matrix from Euler angles (degrees) in ZYX order
mat3 rotateZYX(vec3 angles) {
	vec3 r = radians(angles);
	vec3 c = cos(r), s = sin(r);
	return mat3(
		c.y*c.z, c.y*s.z, -s.y,
		s.x*s.y*c.z - c.x*s.z, s.x*s.y*s.z + c.x*c.z, s.x*c.y,
		c.x*s.y*c.z + s.x*s.z, c.x*s.y*s.z - s.x*c.z, c.x*c.y
	);
}

void main()
{
	vec2 uv = vUV.st;

	// Read previous state (world space)
	vec3 offset = texture(sTD2DInputs[0], uv).rgb;
	vec3 velocity = texture(sTD2DInputs[1], uv).rgb;

	// Read this splat's rest position in world space
	vec4 restData = texture(sTD2DInputs[3], uv);
	vec3 restPos = restData.rgb;
	float valid = restData.a;

	// Skip invalid pixels (no splat mapped here)
	if (valid < 0.5) {
		fragColor[0] = vec4(0.0);
		fragColor[1] = vec4(0.0);
		return;
	}

	// Current world position = rest position + offset
	// Note: restPos already has scene transforms applied (from POP chain)
	vec3 currentWorldPos = restPos + offset;

	// Project current position into Kinect/displacement texture space
	vec4 displaceClipPos = uDisplaceVP * vec4(currentWorldPos, 1.0);
	vec2 displaceUV = displaceClipPos.xy / displaceClipPos.w * 0.5 + 0.5;

	// Sample Kinect flow and compute world-space force
	vec3 force = vec3(0.0);
	float uvMargin = 0.15;  // catch large splats whose centers are just off-screen
	if (all(greaterThanEqual(displaceUV, vec2(-uvMargin))) &&
		all(lessThanEqual(displaceUV, vec2(1.0 + uvMargin))) &&
		displaceClipPos.w > 0.0 &&
		(uMaxDisplaceRadius <= 0.0 || length(restPos - uSceneCenter) < uMaxDisplaceRadius))
	{
		vec3 displaceSample = texture(sTD2DInputs[2], displaceUV).rgb;
		vec2 flow = displaceSample.xy;
		float depth = displaceSample.z;
		float depthWeight = exp(-depth * uDepthFalloff);

		// Convert 2D camera-plane flow to 3D world-space force
		force = (uCamRight * flow.x + uCamUp * flow.y) * uForceStrength;

		// Per-splat noise to scatter trajectories (scales with flow magnitude)
		float flowMag = length(flow);
		vec3 noise = hash3(vec3(uv * 1024.0, uTime * uNoiseSpeed));
		force += noise * flowMag * uForceStrength * uNoiseAmount;
	}

	// Physics integration (all in world space)
	float dt = uDeltaTime;

	velocity += force * dt;					// apply force from Kinect
	velocity *= uDamping;					// heavy damping to prevent overshoot
	offset += velocity * dt;				// integrate position
	offset *= uReturnSpeed;					// exponential decay toward rest position (no overshoot)

	// Safety clamp to prevent runaway splats
	offset = clamp(offset, vec3(-uMaxOffset), vec3(uMaxOffset));

	// Output updated state
	fragColor[0] = vec4(offset, 1.0);		// buffer 0: offset
	fragColor[1] = vec4(velocity, 1.0);		// buffer 1: velocity
}
