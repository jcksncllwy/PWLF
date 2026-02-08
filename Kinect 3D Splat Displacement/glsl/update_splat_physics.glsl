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

// MRT output: set "Number of Color Buffers" to 2 on the GLSL TOP
// Buffer 0 = offset, Buffer 1 = velocity
layout(location = 0) out vec4 fragColor[TD_NUM_COLOR_BUFFERS];

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
	if (all(greaterThanEqual(displaceUV, vec2(0.0))) &&
		all(lessThanEqual(displaceUV, vec2(1.0))) &&
		displaceClipPos.w > 0.0)
	{
		vec3 displaceSample = texture(sTD2DInputs[2], displaceUV).rgb;
		vec2 flow = displaceSample.xy;
		float depth = displaceSample.z;
		float depthWeight = exp(-depth * uDepthFalloff);

		// Convert 2D camera-plane flow to 3D world-space force
		force = (uCamRight * flow.x + uCamUp * flow.y) * uForceStrength * depthWeight;
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
