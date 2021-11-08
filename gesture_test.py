# pyinstaller -D --icon=handicon.ico gesture.py
import csv
import time
import math
import cv2
import numpy as np
import mediapipe as mp
import onnxruntime
import utils


# MediaPipe hands model
mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
hand = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5)

gesture_session = onnxruntime.InferenceSession('onnx/gesture_model.onnx', None)
face_session = onnxruntime.InferenceSession('onnx/facedetector.onnx', None)
input_name = face_session.get_inputs()[0].name
class_names = ["BACKGROUND", "FACE"]

actions = ['palm', 'quiet', 'grab', 'pinch']

# 변수
pTime = 0
swipe_seq = []
before_x = 0
before_y = 0
count = 0
seq_joint = []
frames = []

frame_w = 640
frame_h = 480

hand_data = dict()

# 좌표값 저장
csv_path = 'point_history.csv'
with open(csv_path, 'a', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['Frame num','action', 'angle', 'x1,y1','x2,y2','x3,y3','x4,y4','x5,y5','x6,y6','x7,y7','x8,y8','x9,y9','x10,y10',
                     'x11,y11','x12,y12','x13,y13','x14,y14','x15,y15','x16,y16','x17,y17','x18,y18','x19,y19','x20,y20','x21,y21'])


# cap = cv2.VideoCapture(0)
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc('M', 'J', 'P', 'G'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, frame_w)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_h)
cap.set(cv2.CAP_PROP_FPS, 120)

sx =0
sy =0
ex =0
ey =0

while cap.isOpened():
    ret, image = cap.read()
    boxes, labels, probs = utils.face_detect(image, face_session, input_name)

    try:
        # calc box position
        new_x1, new_x2, new_y2, box, sx, sy, ex, ey = utils.box_pos(boxes)

        # draw gesture region
        cv2.rectangle(image, (new_x1, box[1]), (new_x2, new_y2), (0, 0, 255), 1, cv2.LINE_AA)
        image = cv2.flip(image, 1)
        img_roi = image[sy:ey, sx:ex].copy()
        frame_h, frame_w, _ = img_roi.shape
        img_roi = cv2.cvtColor(img_roi, cv2.COLOR_BGR2RGB)
        hands = hand.process(img_roi)

        # hand
        if hands.multi_hand_landmarks:
            for idx, res in enumerate(hands.multi_hand_landmarks):
                label = hands.multi_handedness[idx].classification[0].label

                joint = np.zeros((21, 4))
                abs_joint = np.zeros((21, 2))

                for j, lm in enumerate(res.landmark):
                    joint[j] = [lm.x, lm.y, lm.z, lm.visibility]
                    abs_joint[j] = [int(lm.x * frame_w + sx), int(lm.y * frame_h + sy)]

                for lm in abs_joint:
                    # 이미지에 손 랜드마크 그림
                    cv2.circle(image, (int(lm[0]), int(lm[1])), 2, (0, 255, 0), -1, cv2.LINE_AA)
                    seq_joint.append(joint)

                    # 손가락 포인트의 각도 계산
                    angle = utils.calc_angle(joint)
                    d = np.concatenate([joint.flatten(), angle])

                    # 예측 정확도 및 예측 인덱스 뽑기
                    conf, i_pred = utils.calc_predict(d, gesture_session)
                    if conf < 0.9:
                        continue

                    # 제스처 이름 받아옴
                    action = actions[i_pred]

                    # swipe 알고리즘
                    if action == 'swipe':
                        swipe_seq.append(action)

                        if len(swipe_seq) == 1:
                            before_x = joint[12][0]
                            before_y = joint[12][1]

                        if len(swipe_seq) >= 8:
                            if abs(before_x - joint[12][0]) >= 0.2:
                                if before_x > joint[12][0]:
                                    action = 'left'
                                    swipe_seq = []
                                elif before_x < joint[12][0]:
                                    action = 'right'
                                    swipe_seq = []
                            if abs(before_y - joint[12][1]) >= 0.2:
                                if before_y > joint[12][1]:
                                    action = 'up'
                                    swipe_seq = []
                                elif before_y < joint[12][1]:
                                    action = 'down'
                                    swipe_seq = []

                    elif action != 'swipe':
                        swipe_seq = []

                    # grab 각도 계산
                    if action == 'grab':
                        if label == 'Left':
                            grab_angle = (math.degrees(math.atan2(joint[3][1] - joint[17][1],
                                                              joint[3][0] - joint[17][0])))
                        else:
                            grab_angle = (math.degrees(math.atan2(joint[17][1] - joint[3][1],
                                                              joint[17][0] - joint[3][0])))

                        utils.draw_timeline(image, angle, abs_joint)

                    cv2.putText(image, f'{action.upper()}',
                                org=(int(abs_joint[0][0]), int(abs_joint[0][1] + 20)),
                                fontFace=cv2.FONT_HERSHEY_SIMPLEX, fontScale=1, color=(255, 255, 255), thickness=2)

                    if action == 'grab':
                        utils.logging_csv(csv_path, count, action, grab_angle, abs_joint)
                        utils.save_dict(hand_data, abs_joint, action, grab_angle)
                    else:
                        utils.logging_csv(csv_path, count, action, 'None', abs_joint)
                        utils.save_dict(hand_data, abs_joint, action, 'None')

                print(count, action)
                print(hand_data)

        else:
            # 보간
            if len(seq_joint) >= 2:
                new_joint = np.zeros((21, 3))
                for j1, j2 in zip(seq_joint[-2], seq_joint[-1]):
                    for idx in range(21):
                        x = (j1[idx][0] + j2[idx][0]) // 2
                        y = (j1[idx][1] + j2[idx][1]) // 2
                        z = (j1[idx][2] + j2[idx][2]) // 2
                        new_joint[idx] = [x, y, z]

                print(new_joint)
            else:
                continue

    except:
        print("Face detecting error!")


    cTime = time.time()
    fps = 1 / (cTime - pTime)
    pTime = cTime

    cv2.putText(image, f"FPS : {fps:.2f}", (10, 50), cv2.FONT_HERSHEY_TRIPLEX, 1, (255, 0, 0), 1)
    cv2.imshow('img', image)

    count += 1
    if cv2.waitKey(1) == 27:
        break

cap.release()
cv2.destroyAllWindows()