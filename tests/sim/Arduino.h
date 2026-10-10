/*
 * Host-side stand-in for the Arduino/ESP32 core, used by tests/test_runtime.py.
 *
 * It lets the C++ that Iotift generates be compiled with the host g++ and
 * *run*, with simulated time, pins, ADC, PWM and Serial.  Every observable
 * side effect is printed as a line "[<ms>] <event>" so tests can assert on
 * behaviour, not on the text of the generated code.
 *
 * Only what generated code (and the examples' raw C blocks) actually use is
 * modelled.  Arduino.h macros that commonly clash with user identifiers
 * (PI, HIGH, DEC, ...) are defined as real macros on purpose, so a clash
 * fails here the same way it fails on the device.
 */
#pragma once
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <string>

typedef bool boolean;
typedef uint8_t byte;

#define ARDUINO_ARCH_ESP32 1
#define PI 3.1415926535897932384626433832795
#define HALF_PI 1.5707963267948966192313216916398
#define TWO_PI 6.283185307179586476925286766559
#define DEG_TO_RAD 0.017453292519943295769236907684886
#define RAD_TO_DEG 57.295779513082320876798154814105
#define DEC 10
#define HEX 16
#define OCT 8
#define BIN 2
#define HIGH 1
#define LOW 0
#define INPUT 0x01
#define OUTPUT 0x03
#define INPUT_PULLUP 0x05
#define INPUT_PULLDOWN 0x09
#define RISING 0x01
#define FALLING 0x02
#define CHANGE 0x03
#define IRAM_ATTR
/* ESP32 ADC pin names */
#define A0 36
#define A3 39
#define A4 32
#define A5 33
#define A6 34
#define A7 35
#define F(x) x
#define portMAX_DELAY 0xffffffff
#define pdMS_TO_TICKS(x) (x)
typedef int gpio_num_t;

/* ── simulator state (defined in sim.cpp) ── */
extern unsigned long g_now;
extern int g_pin[64];
extern int g_analog[64];
extern int g_ledc[16];
extern int g_pin_mode[64];
extern void (*g_isr[64])(void);
extern int g_isr_mode[64];

static inline unsigned long millis() { return g_now; }
static inline unsigned long micros() { return g_now * 1000UL; }
static inline void delay(unsigned long ms) { g_now += ms; }
static inline void delayMicroseconds(unsigned int) {}
static inline void yield() {}

static inline void pinMode(int p, int m) {
  g_pin_mode[p] = m;
  if (m == INPUT_PULLUP) g_pin[p] = 1;          /* idle level of a pulled-up input */
  if (m == INPUT_PULLDOWN) g_pin[p] = 0;
  printf("[%lu] pinMode(%d,%d)\n", g_now, p, m);
}
static inline void digitalWrite(int p, int v) {
  if (g_pin[p] != (v ? 1 : 0)) printf("[%lu] PIN %d -> %d\n", g_now, p, v ? 1 : 0);
  g_pin[p] = v ? 1 : 0;
}
static inline int digitalRead(int p) { return g_pin[p]; }
static inline int analogRead(int p) { return g_analog[p]; }
static inline void analogWrite(int p, int v) { printf("[%lu] analogWrite(%d,%d)\n", g_now, p, v); }
static inline void dacWrite(int p, int v) { printf("[%lu] dacWrite(%d,%d)\n", g_now, p, v); }
static inline int digitalPinToInterrupt(int p) { return p; }
static inline void attachInterrupt(int p, void (*f)(void), int m) {
  g_isr[p] = f; g_isr_mode[p] = m;
  printf("[%lu] attachInterrupt(%d,%d)\n", g_now, p, m);
}
static inline void detachInterrupt(int p) { g_isr[p] = 0; }
static inline void noInterrupts() {}
static inline void interrupts() {}

/* ESP32 core 2.x LEDC API */
static inline double ledcSetup(int ch, double f, int bits) {
  printf("[%lu] ledcSetup(ch%d,%g,%d)\n", g_now, ch, f, bits);
  return f;
}
static inline void ledcAttachPin(int pin, int ch) { printf("[%lu] ledcAttachPin(%d,ch%d)\n", g_now, pin, ch); }
static inline void ledcWrite(int ch, uint32_t d) {
  if (g_ledc[ch] != (int)d) printf("[%lu] ledcWrite(ch%d,%u)\n", g_now, ch, d);
  g_ledc[ch] = (int)d;
}

static inline long random(long hi) { return hi ? rand() % hi : 0; }
static inline long random(long lo, long hi) { return lo + random(hi - lo); }
static inline long map(long x, long a, long b, long c, long d) { return (x - a) * (d - c) / (b - a) + c; }

struct EspClass {
  void restart() { printf("[%lu] ESP.restart\n", g_now); exit(0); }
};
static EspClass ESP;

class String : public std::string {
 public:
  String() {}
  String(const char *s) : std::string(s ? s : "") {}
  String(const std::string &s) : std::string(s) {}
  String(int v) : std::string(std::to_string(v)) {}
  String(unsigned v) : std::string(std::to_string(v)) {}
  String(long v) : std::string(std::to_string(v)) {}
  String(unsigned long v) : std::string(std::to_string(v)) {}
  String(double v, int digits = 2) { char b[64]; snprintf(b, 64, "%.*f", digits, v); assign(b); }
  String(float v, int digits = 2) : String((double)v, digits) {}
  String(char c) : std::string(1, c) {}
  int toInt() const { return atoi(c_str()); }
  float toFloat() const { return (float)atof(c_str()); }
  String substring(size_t a) const { return a < size() ? String(substr(a)) : String(); }
  String substring(size_t a, size_t b) const { return a < size() ? String(substr(a, b - a)) : String(); }
  bool startsWith(const String &p) const { return compare(0, p.size(), p) == 0; }
  int indexOf(char c) const { size_t i = find(c); return i == npos ? -1 : (int)i; }
  void trim() {
    size_t a = find_first_not_of(" \r\n\t"), b = find_last_not_of(" \r\n\t");
    if (a == npos) { clear(); return; }
    assign(substr(a, b - a + 1));
  }
};

/* Serial: buffers a line and prints it as "[ms] SERIAL: <text>" on newline. */
struct HardwareSerial {
  std::string line;
  void begin(unsigned long) {}
  void out(const String &s) { line += s; }
  void nl();
  template <class T> void print(T v) { out(String(v)); }
  void print(const char *s) { out(String(s)); }
  void print(const String &s) { out(s); }
  void print(double v, int d) { out(String(v, d)); }
  void print(bool b) { out(String((int)b)); }
  template <class T> void println(T v) { print(v); nl(); }
  void println(double v, int d) { print(v, d); nl(); }
  void println() { nl(); }
  void printf(const char *fmt, ...);
  int available() { return 0; }
  int read() { return -1; }
  String readStringUntil(char) { return String(); }
  void flush() {}
  operator bool() { return true; }
};
extern HardwareSerial Serial;
