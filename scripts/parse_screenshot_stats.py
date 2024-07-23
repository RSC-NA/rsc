#!/usr/bin/env python3

import argparse
import os
import sys
from pathlib import Path

import cv2
import imutils
import matplotlib.pyplot as plt
import numpy as np
import pytesseract
from PIL import Image


def parse(screenshot: str):

    # load the image and convert it to grayscale
    image = cv2.imread(screenshot)
    # cv2.imshow("Original", image)

    gray = cv2.threshold(image, 200, 255, cv2.THRESH_BINARY)[1]
    gray = cv2.resize(gray, (0, 0), fx=3, fy=3)
    gray = cv2.medianBlur(gray, 9)

    image2 = cv2.imread(screenshot, cv2.IMREAD_COLOR)
    gray2 = cv2.cvtColor(image2, cv2.COLOR_BGR2GRAY)
    # sharpen_kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
    # sharpen = cv2.filter2D(gray2, -1, sharpen_kernel)

    ttype = cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    print(f"THRESH_BINARY_INV: {cv2.THRESH_BINARY_INV}")
    print(f"THRES OTSU: {cv2.THRESH_OTSU}")
    print(f"THRES OTSU+BINARY: {ttype}")
    thresh = cv2.threshold(gray2, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    # thresh = cv2.threshold(sharpen, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

    # blurred = cv2.blur(image, (3,3))
    img = Image.fromarray(image)
    grayimg = Image.fromarray(gray)
    gray2img = Image.fromarray(thresh)

    out = Path(screenshot).parent / "gray.jpg"
    out2 = Path(screenshot).parent / "gray2.jpg"
    grayimg.save(out)
    gray2img.save(out2)
    # cv2.imshow("Gray", gray)
    # cv2.waitKey()
    originaltext = pytesseract.image_to_string(img, lang="eng")
    graytext = pytesseract.image_to_string(thresh, lang="eng")
    print(f"Original:\n{originaltext}")
    print(f"Gray:\n{graytext.split()}")

    # data = pytesseract.image_to_data(img, lang="eng", output_type=pytesseract.Output.STRING)
    # gdata = pytesseract.image_to_data(grayimg, lang="eng", output_type=pytesseract.Output.STRING)
    # print(f"Data: {data}")
    # print(f"Data: {gdata}")


def roi(screenshot):
    im = cv2.imread(screenshot)
    im = cv2.resize(im, (2000, 1000))
    # cv2.imshow("Resize", im)
    # cv2.waitKey()

    gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (9, 9), 0)
    thresh = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 30
    )
    # thresh = cv2.threshold(gray,0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]

    # Display thresh image
    cv2.imshow("Thresh", thresh)
    cv2.waitKey(0)

    # Dilate to combine adjacent text contours
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    dilate = cv2.dilate(thresh, kernel, iterations=15)

    # Display thresh image
    cv2.imshow("Dilate", dilate)
    cv2.waitKey(0)

    # Find contours, highlight text areas, and extract ROIs
    cnts = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    # cnts = cv2.findContours(dilate, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = cnts[0] if len(cnts) == 2 else cnts[1]

    # Find contours keeping only largest
    # cnts = sorted(cnts, key=cv3.contourArea, reverse=True)[:4]
    print(f"cnts: {cnts}")

    image = None
    line_items_coordinates = []
    for c in cnts:
        area = cv2.contourArea(c)
        x, y, w, h = cv2.boundingRect(c)
        print(f"x: {x} y: {y} w: {w} h: {h}")

        # get largest
        # roi = gray[y - 5:y + h + 5, x - 5:x + w + 5]

        # display the character, making it large enough for us

        # to see, then wait for a keypress
        # cv2.imshow("ROI", imutils.resize(roi, width=28))
        # key = cv2.waitKey(0)

        if y >= 600 and x <= 1000:
            if area > 10000:
                image = cv2.rectangle(
                    im, (x, y), (2200, y + h), color=(255, 0, 255), thickness=3
                )
                line_items_coordinates.append([(x, y), (2200, y + h)])

        if y >= 2400 and x <= 2000:
            image = cv2.rectangle(
                im, (x, y), (2200, y + h), color=(255, 0, 255), thickness=3
            )
            line_items_coordinates.append([(x, y), (2200, y + h)])

    return image, line_items_coordinates


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parse RL lobby stats from screenshot")
    parser.add_argument(
        "screenshot", type=str, help="Screenshot of final lobby scoreboard"
    )
    argv = parser.parse_args()

    if not Path(argv.screenshot).exists():
        print(f"Error: {argv.screenshot} does not exist.")
        sys.exit(1)

    parse(argv.screenshot)
    image, line_items = roi(argv.screenshot)
    cv2.imshow("ROI", image)
    cv2.waitKey()
    print(f"Line Items: {line_items}")
