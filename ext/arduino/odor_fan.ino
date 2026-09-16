const int FAN=9, G=5, Y=6, R=7, GAS=A0;
String buf;
void setLed(int g,int y,int r){digitalWrite(G,g);digitalWrite(Y,y);digitalWrite(R,r);}
void setup(){
  Serial.begin(9600); pinMode(FAN,OUTPUT); pinMode(G,OUTPUT);
  pinMode(Y,OUTPUT); pinMode(R,OUTPUT); setLed(1,0,0);
}
void loop(){
  while(Serial.available()){
    char ch=Serial.read();
    if(ch=='\n'){ handle(buf); buf=""; } else buf+=ch;
  }
  static unsigned long t=0;
  if(millis()-t>2000){t=millis(); Serial.print("GAS:"); Serial.println(analogRead(GAS));}
}
void handle(String s){
  s.trim();
  if(s=="RISK:LOW"){setLed(1,0,0); digitalWrite(FAN,LOW);}
  else if(s=="RISK:MEDIUM"){setLed(0,1,0); digitalWrite(FAN,LOW);}
  else if(s=="RISK:HIGH"){setLed(0,0,1); digitalWrite(FAN,HIGH);}
  else if(s=="FAN:ON") digitalWrite(FAN,HIGH);
  else if(s=="FAN:OFF") digitalWrite(FAN,LOW);
  Serial.print("ACK:"); Serial.println(s);
}

