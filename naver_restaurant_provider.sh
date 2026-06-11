#!/bin/sh

naver_get_restaurants_by_food() {
  food_name=$1
  location=$2

  SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
  python3 "$SCRIPT_DIR/naver_restaurant_api.py" --query "$food_name" --location "$location"
}
