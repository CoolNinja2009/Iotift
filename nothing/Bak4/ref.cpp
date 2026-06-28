// ===== Pins =====
const int buttonPin = 4;
const int buzzerPin = 18;

// ===== PWM Config =====
const int pwmChannel = 0;
const int pwmFreq = 2000;   // Hz
const int pwmResolution = 8;

// ===== Timing =====
const unsigned long FULL_BUDGET = 30000;      // 30 sec per hour
const unsigned long HOUR = 3600000;

const unsigned long MAX_BURST = 5000;         // 5 sec max continuous
const unsigned long COOLDOWN = 2000;          // 2 sec cooldown

// ===== State =====
unsigned long honkUsed = 0;
unsigned long lastReset = 0;

unsigned long burstStart = 0;
unsigned long lastReleaseTime = 0;

bool inBurst = false;
bool inCooldown = false;

void setup() {
  pinMode(buttonPin, INPUT_PULLUP);

  ledcSetup(pwmChannel, pwmFreq, pwmResolution);
  ledcAttachPin(buzzerPin, pwmChannel);

  ledcWrite(pwmChannel, 0); // OFF

  lastReset = millis();
}

void loop() {
  unsigned long now = millis();
  bool buttonPressed = (digitalRead(buttonPin) == LOW);

  // ===== Reset hourly budget =====
  if (now - lastReset >= HOUR) {
    honkUsed = 0;
    lastReset = now;
  }

  // ===== Cooldown logic =====
  if (inCooldown) {
    if (now - lastReleaseTime >= COOLDOWN) {
      inCooldown = false;
    } else {
      stopBuzzer();
      return;
    }
  }

  // ===== Button handling =====
  if (buttonPressed) {

    // Start burst
    if (!inBurst) {
      inBurst = true;
      burstStart = now;
    }

    // Check burst limit
    if (now - burstStart >= MAX_BURST) {
      inBurst = false;
      inCooldown = true;
      lastReleaseTime = now;
      stopBuzzer();
      return;
    }

    // ===== Volume control =====
    if (honkUsed < FULL_BUDGET) {
      setFullVolume();
      honkUsed += 10; // approx increment (loop delay ~10ms)
    } else {
      setReducedVolume();
    }

  } else {
    // Button released
    if (inBurst) {
      inBurst = false;
      inCooldown = true;
      lastReleaseTime = now;
    }
    stopBuzzer();
  }

  delay(10); // small loop delay
}

// ===== Helper functions =====

void setFullVolume() {
  ledcWrite(pwmChannel, 255); // 100%
}

void setReducedVolume() {
  ledcWrite(pwmChannel, 120); // ~50%
}

void stopBuzzer() {
  ledcWrite(pwmChannel, 0);
}