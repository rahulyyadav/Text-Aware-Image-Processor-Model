import cv2
import pytesseract

#load an image
img = cv2.imread("data/test.jpeg")
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

#show the image
# cv2.imshow("Image", gray)
# cv2.waitKey(0)
# cv2.destroyAllWindows()

#try OCR
text = pytesseract.image_to_string(gray)
print("Extracted text: ", text)

